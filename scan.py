from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", "venv", ".venv",
    "dist", "build", "target", ".idea", ".vscode",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    # 同梱されたサードパーティコードの README をプロジェクトとして拾わないよう除外
    "vendor", "wp-admin", "wp-includes",
}
TREE_MAX_DEPTH = 3
README_SCAN_LINES = 30
DESCRIPTION_MAX_LEN = 120
PC_DATA_DIR = "pc-data"
PROJECTS_SUBDIR = "projects"
ENV_FILES = ("env.json", "env.md", "packages.txt")
UNKNOWN = "取得できず"


# ── ヘルパー ──────────────────────────────────────────────────────────────────

def sanitize_hostname(raw: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", raw)


def get_stable_hostname() -> str:
    # macOS の socket.gethostname() はネットワーク（DHCP/mDNS）依存で変わるため、
    # ユーザー設定で固定される LocalHostName を優先する
    if sys.platform == "darwin":
        result = subprocess.run(["scutil", "--get", "LocalHostName"],
                                capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return socket.gethostname()


def ensure_data_git_repo(data_root: Path) -> bool:
    """data/ を git リポジトリとして初期化する。初回のみ True を返す。"""
    if (data_root / ".git").exists():
        return False
    data_root.mkdir(exist_ok=True)
    subprocess.run(["git", "init"], cwd=data_root, check=True, capture_output=True)
    gitignore = data_root / ".gitignore"
    gitignore.write_text("index.md\n", encoding="utf-8")
    return True


# ── スキャン ──────────────────────────────────────────────────────────────────

def find_projects(dev_root: Path, self_path: Path) -> list[Path]:
    results = []
    for dirpath, dirs, files in os.walk(dev_root, topdown=True, followlinks=False):
        current = Path(dirpath).resolve()
        if current == self_path:
            dirs.clear()
            continue
        # 隠しディレクトリ（.pytest_cache 等）は自動生成 README を拾わないよう探索対象外
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        if "README.md" in files:
            results.append(current)
            dirs.clear()  # プロジェクトルートが見つかったらサブは掘らない
        elif "pmo" in dirs and (current / "pmo" / "README.md").exists():
            # ルートに README がなくても pmo/ があればプロジェクトルート。
            # 配下（data/ のバックアップ等）に潜ると同梱物の README を誤登録するため掘らない
            results.append(current)
            dirs.clear()
    return results


def make_project_key(project_path: Path, dev_root: Path) -> str:
    parts = project_path.relative_to(dev_root).parts
    return "__".join(parts)


def generate_tree(root: Path, max_depth: int = TREE_MAX_DEPTH) -> str:
    lines = [root.name + "/"]

    def _walk(path: Path, prefix: str, depth: int):
        if depth >= max_depth:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return
        entries = [e for e in entries if e.name not in SKIP_DIRS]
        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            suffix = "/" if entry.is_dir() and not entry.is_symlink() else ""
            lines.append(prefix + connector + entry.name + suffix)
            if entry.is_dir() and not entry.is_symlink():
                extension = "    " if is_last else "│   "
                _walk(entry, prefix + extension, depth + 1)

    _walk(root, "", 0)
    return "\n".join(lines)


def get_last_activity(project_path: Path) -> str:
    """最終更新日 (YYYY-MM-DD)。git の最終コミット日、なければ README.md（なければ pmo/README.md）の mtime。"""
    result = subprocess.run(["git", "log", "-1", "--format=%cs"],
                            cwd=project_path, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    try:
        ts = main_readme(project_path).stat().st_mtime
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except OSError:
        return ""


def main_readme(project_path: Path) -> Path:
    """説明の元になる README。ルートに無ければ pmo/README.md（pmo/ だけを持つプロジェクト）。"""
    root_readme = project_path / "README.md"
    return root_readme if root_readme.exists() else project_path / "pmo" / "README.md"


def extract_description(readme_path: Path) -> str:
    try:
        text = readme_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "*(no description)*"

    lines = text.splitlines()[:README_SCAN_LINES]
    found_heading = False
    for line in lines:
        stripped = line.strip()
        if not found_heading:
            if stripped.startswith("#"):
                found_heading = True
            continue
        if not stripped or stripped.startswith("#"):
            continue
        cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", stripped)
        cleaned = re.sub(r"[*_`~]+", "", cleaned)
        cleaned = cleaned.strip()
        if cleaned:
            if len(cleaned) > DESCRIPTION_MAX_LEN:
                cleaned = cleaned[:DESCRIPTION_MAX_LEN - 1] + "…"
            return cleaned

    return "*(no description)*"


# ── 環境点検 ──────────────────────────────────────────────────────────────────
# OS の更新状況を記録する。PC の環境は変更しない（読み取り専用のコマンドだけを使う）

def run_cmd(args: list[str], timeout: int = 30) -> str | None:
    """コマンドの標準出力。失敗・タイムアウト・コマンドなしは None。"""
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                                errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def read_os_release() -> str:
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8")
    except OSError:
        return UNKNOWN
    m = re.search(r'^PRETTY_NAME="?([^"\n]*)"?', text, re.M)
    return m.group(1) if m else UNKNOWN


def last_apt_upgrade() -> str:
    """apt の履歴から、パッケージを更新した最後の日時。"""
    log_dir = Path("/var/log/apt")
    logs = sorted(log_dir.glob("history.log.*.gz"), key=lambda p: int(p.name.split(".")[2]))
    for log in [log_dir / "history.log", *logs]:  # 新しい順
        try:
            text = (gzip.open(log, "rt", errors="replace").read() if log.suffix == ".gz"
                    else log.read_text(errors="replace"))
        except OSError:
            continue
        for block in reversed(text.strip().split("\n\n")):
            if re.search(r"^Upgrade:", block, re.M):
                m = re.search(r"^Start-Date:\s*(.+)$", block, re.M)
                if m:
                    return re.sub(r"\s+", " ", m.group(1).strip())
    return UNKNOWN


def last_apt_list_update() -> str:
    """最後に apt update した日時（パッケージ一覧の取得時刻）。"""
    try:
        ts = max(p.stat().st_mtime for p in Path("/var/lib/apt/lists").iterdir() if p.is_file())
    except (OSError, ValueError):
        return UNKNOWN
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def apt_upgradable() -> dict:
    out = run_cmd(["apt", "list", "--upgradable"], timeout=60)
    if out is None:
        return {"count": None, "security": []}
    pkgs = [line for line in out.splitlines() if "/" in line and "[upgradable" in line]
    security = [line.split("/")[0] for line in pkgs if "-security" in line.split()[0]]
    return {"count": len(pkgs), "security": security}


def collect_linux() -> dict:
    upgradable = apt_upgradable()
    return {
        "os": read_os_release(),
        "kernel": (run_cmd(["uname", "-r"]) or UNKNOWN).strip(),
        "last_upgrade": last_apt_upgrade(),
        "last_list_update": last_apt_list_update(),
        "pending": upgradable["count"],
        "pending_security": upgradable["security"],
    }


# PowerShell の既定の出力は Shift-JIS で文字化けするため UTF-8 を指定する
PS_PREFIX = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
PS_OS_INFO = (
    '$os=Get-CimInstance Win32_OperatingSystem; '
    '$ubr=(Get-ItemProperty "HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion").UBR; '
    '$hf=Get-HotFix | Where-Object InstalledOn | Sort-Object InstalledOn -Descending | Select-Object -First 1; '
    '[pscustomobject]@{caption=$os.Caption; build="$($os.BuildNumber).$ubr"; '
    'last_hotfix=$hf.HotFixID; last_hotfix_date=$hf.InstalledOn.ToString("yyyy-MM-dd")} | ConvertTo-Json -Compress'
)
# 未適用の更新を検索するだけ（ダウンロード・インストールはしない）
PS_PENDING = (
    '$r=(New-Object -ComObject Microsoft.Update.Session).CreateUpdateSearcher().Search("IsInstalled=0 and IsHidden=0"); '
    'ConvertTo-Json -Compress @(@($r.Updates | ForEach-Object { $_.Title }))'
)


def run_powershell(script: str, timeout: int) -> object | None:
    # Windows 側のコマンドは WSL の cwd が UNC パスだと警告を出すため、Windows のドライブ上で実行する
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", PS_PREFIX + script],
                                capture_output=True, text=True, timeout=timeout,
                                encoding="utf-8", errors="replace", cwd="/mnt/c")
        return json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def wsl_version() -> str:
    try:
        result = subprocess.run(["wsl.exe", "--version"], capture_output=True, timeout=30, cwd="/mnt/c")
    except (OSError, subprocess.TimeoutExpired):
        return UNKNOWN
    text = result.stdout.decode("utf-16-le", errors="replace")
    first = text.replace("\r", "").strip().splitlines()[:1]
    return first[0].split(":")[-1].strip() if first else UNKNOWN


def collect_windows_from_wsl() -> dict:
    info = run_powershell(PS_OS_INFO, timeout=60) or {}
    pending = run_powershell(PS_PENDING, timeout=120)
    return {
        "os": f"{info.get('caption', UNKNOWN)} (build {info.get('build', '?')})" if info else UNKNOWN,
        "last_upgrade": (f"{info.get('last_hotfix_date')} ({info.get('last_hotfix')})"
                         if info.get("last_hotfix") else UNKNOWN),
        "pending": len(pending) if isinstance(pending, list) else None,
        "pending_titles": pending if isinstance(pending, list) else [],
        "wsl_version": wsl_version(),
    }


def collect_macos() -> dict:
    sw = run_cmd(["sw_vers"]) or ""
    name = re.search(r"ProductName:\s*(.+)", sw)
    ver = re.search(r"ProductVersion:\s*(.+)", sw)
    build = re.search(r"BuildVersion:\s*(.+)", sw)
    os_name = (f"{name.group(1).strip()} {ver.group(1).strip()} ({build.group(1).strip()})"
               if name and ver and build else UNKNOWN)

    last = UNKNOWN
    history = run_cmd(["softwareupdate", "--history"], timeout=60)
    if history:
        dates = []
        for line in history.splitlines():
            # XProtect などの定義データは自動で入るため、OS の更新としては数えない
            if re.search(r"XProtect|MRT|Gatekeeper|ConfigData|Configuration Data", line):
                continue
            m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", line)
            try:
                if m:
                    dates.append(datetime.strptime(m.group(1), "%m/%d/%Y"))
            except ValueError:
                pass
        if dates:
            last = max(dates).strftime("%Y-%m-%d")

    # 未適用の更新を Apple に問い合わせるだけ（インストールはしない）
    listing = run_cmd(["softwareupdate", "-l"], timeout=120)
    titles = (re.findall(r"^\s*\* Label:\s*(.+)$", listing, re.M) if listing is not None else [])
    return {
        "os": os_name,
        "last_upgrade": last,
        "pending": len(titles) if listing is not None else None,
        "pending_titles": titles,
    }


def collect_packages() -> str:
    if sys.platform == "darwin":
        return run_cmd(["brew", "list", "--versions"], timeout=60) or ""
    return run_cmd(["dpkg-query", "-W", "-f=${Package} ${Version}\n"], timeout=60) or ""


def collect_env() -> dict:
    env: dict = {"checked_at": datetime.now().astimezone().isoformat()}
    if sys.platform == "darwin":
        env["macos"] = collect_macos()
    elif sys.platform.startswith("linux"):
        env["linux"] = collect_linux()
        if is_wsl():
            env["windows"] = collect_windows_from_wsl()
    return env


def fmt_pending(n: int | None, security: list | None = None) -> str:
    if n is None:
        return UNKNOWN
    return f"{n} 件（セキュリティ {len(security)} 件）" if security is not None else f"{n} 件"


def env_summary_rows(env: dict) -> list[tuple[str, str, str, str]]:
    """(区分, OS, 最終更新, 更新待ち) の行。"""
    rows = []
    if "linux" in env:
        x = env["linux"]
        rows.append(("Linux" + (" (WSL)" if "windows" in env else ""), x["os"],
                     x["last_upgrade"], fmt_pending(x["pending"], x["pending_security"])
                     + f" ※ apt update: {x['last_list_update']} 時点"))
    if "windows" in env:
        x = env["windows"]
        rows.append(("Windows", x["os"], x["last_upgrade"], fmt_pending(x["pending"])))
    if "macos" in env:
        x = env["macos"]
        rows.append(("macOS", x["os"], x["last_upgrade"], fmt_pending(x["pending"])))
    return rows


def write_env(env: dict, packages: str, pc_root: Path, hostname: str):
    (pc_root / "env.json").write_text(json.dumps(env, indent=2, ensure_ascii=False), encoding="utf-8")
    (pc_root / "packages.txt").write_text(packages, encoding="utf-8")

    lines = [f"# PC Environment — {hostname}", "",
             f"Checked: {env['checked_at'][:16].replace('T', ' ')}", "",
             "| 区分 | OS | 最終更新 | 更新待ち |", "|------|----|----------|----------|"]
    lines += [f"| {' | '.join(r)} |" for r in env_summary_rows(env)]
    if "linux" in env:
        x = env["linux"]
        lines += ["", "## Linux", "", f"- カーネル: {x['kernel']}",
                  f"- セキュリティ更新待ち: {', '.join(x['pending_security']) or 'なし'}"]
    if "windows" in env:
        x = env["windows"]
        lines += ["", "## Windows", "", f"- WSL: {x['wsl_version']}", "- 未適用の更新:"]
        lines += [f"  - {t}" for t in x["pending_titles"]] or ["  - なし"]
    if "macos" in env:
        lines += ["", "## macOS", "", "- 未適用の更新:"]
        lines += [f"  - {t}" for t in env["macos"]["pending_titles"]] or ["  - なし"]
    lines += ["", "パッケージの一覧: `packages.txt`", ""]
    (pc_root / "env.md").write_text("\n".join(lines), encoding="utf-8")


# ── 書き込み ──────────────────────────────────────────────────────────────────

def write_project_data(project_path: Path, key: str, pc_root: Path, dev_root: Path) -> dict:
    out_dir = pc_root / PROJECTS_SUBDIR / key
    out_dir.mkdir(parents=True, exist_ok=True)

    if (project_path / "README.md").exists():
        shutil.copy2(project_path / "README.md", out_dir / "README.md")
    (out_dir / "tree.txt").write_text(generate_tree(project_path), encoding="utf-8")

    pmo_readme = project_path / "pmo" / "README.md"
    has_pmo = pmo_readme.exists()
    if has_pmo:
        pmo_out = out_dir / "pmo"
        pmo_out.mkdir(exist_ok=True)
        shutil.copy2(pmo_readme, pmo_out / "README.md")

    rel = "~/" + str(project_path.relative_to(Path.home()))
    description = extract_description(main_readme(project_path))
    return {"key": key, "path": rel, "has_pmo": has_pmo,
            "last_activity": get_last_activity(project_path),
            "description": description}


def write_pc_meta(entries: list[dict], pc_root: Path, hostname: str, hostname_raw: str, dev_root: Path):
    meta = {
        "hostname": hostname,
        "hostname_raw": hostname_raw,
        "scanned_at": datetime.now().astimezone().isoformat(),
        "project_count": len(entries),
        "scan_root": "~/dev",
    }
    (pc_root / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def write_pc_entries(entries: list[dict], pc_root: Path):
    (pc_root / "entries.json").write_text(
        json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def write_pc_index(entries: list[dict], pc_root: Path, hostname: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = "\n".join(
        f"| {e['key']} | {e['path']} | {'YES' if e['has_pmo'] else ''} |"
        f" {e.get('last_activity') or '-'} | {e['description']} |"
        for e in sorted(entries, key=lambda e: e["key"])
    )
    content = (
        f"# Dev Projects Index — {hostname}\n\n"
        f"Scanned: {now}  |  Projects: {len(entries)}\n\n"
        f"| Project Key | Path | Main | Updated | Description |\n"
        f"|-------------|------|:----:|:-------:|-------------|\n"
        f"{rows}\n"
    )
    (pc_root / "index.md").write_text(content, encoding="utf-8")


def discover_pc_data(data_root: Path) -> list[dict]:
    pc_dir = data_root / PC_DATA_DIR
    if not pc_dir.is_dir():
        return []
    results = []
    for subdir in sorted(pc_dir.iterdir()):
        if not subdir.is_dir():
            continue
        try:
            meta = json.loads((subdir / "meta.json").read_text(encoding="utf-8"))
            entries = json.loads((subdir / "entries.json").read_text(encoding="utf-8"))
            try:
                env = json.loads((subdir / "env.json").read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                env = None
            results.append({"hostname": meta.get("hostname", subdir.name),
                            "scanned_at": meta.get("scanned_at", ""),
                            "entries": entries, "env": env})
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Warning: {subdir.name} をスキップ ({e})", flush=True)
    return results


def write_merged_index(data_root: Path) -> int:
    pc_data = discover_pc_data(data_root)
    if not pc_data:
        return 0

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pc_names = sorted(pc["hostname"] for pc in pc_data)
    pc_header = "  ".join(
        f"{pc['hostname']} ({pc['scanned_at'][:16].replace('T', ' ')})"
        for pc in pc_data
    )

    # path をキーにして PC ごとのエントリを集約
    by_path: dict[str, dict[str, dict]] = defaultdict(dict)
    for pc in pc_data:
        for e in pc["entries"]:
            by_path[e["path"]][pc["hostname"]] = e

    unique = len(by_path)
    cross_pc = sum(1 for pcs in by_path.values() if len(pcs) > 1)
    total_raw = sum(len(pcs) for pcs in by_path.values())

    # サマリ
    pc_col_header = " | ".join(pc_names)
    pc_col_sep = " | ".join(":-:" for _ in pc_names)
    rows = []
    recent = []
    for path in sorted(by_path.keys()):
        pcs = by_path[path]
        best = next((e for e in pcs.values() if e.get("has_pmo")), next(iter(pcs.values())))
        updated = max((e.get("last_activity") or "" for e in pcs.values()), default="")
        cols = []
        for pc in pc_names:
            if pc not in pcs:
                cols.append("-")
            elif pcs[pc].get("has_pmo"):
                cols.append("Main")
            else:
                cols.append("clone")
        rows.append(f"| {path} | {' | '.join(cols)} | {updated or '-'} | {best['description']} |")
        if updated:
            recent.append((updated, path, best["description"]))

    recent.sort(reverse=True)
    recent_rows = "\n".join(
        f"| {updated} | {path} | {desc} |"
        for updated, path, desc in recent[:15]
    )
    rows_str = "\n".join(rows)
    env_rows = []
    for pc in pc_data:
        if not pc["env"]:
            env_rows.append(f"| {pc['hostname']} | 未点検 | - | - | - | - |")
            continue
        checked = pc["env"]["checked_at"][:16].replace("T", " ")
        env_rows += [f"| {pc['hostname']} | {checked} | {' | '.join(r)} |"
                     for r in env_summary_rows(pc["env"])]
    env_rows_str = "\n".join(env_rows)
    content = (
        f"# Dev Projects Index (All PCs)\n\n"
        f"Last merged: {now}\n"
        f"PCs: {pc_header}\n\n"
        f"## PC環境（OS の更新状況）\n\n"
        f"| PC | 点検日時 | 区分 | OS | 最終更新 | 更新待ち |\n"
        f"|----|----------|------|----|----------|----------|\n"
        f"{env_rows_str}\n\n"
        f"## サマリ\n\n"
        f"| 区分 | 件数 |\n"
        f"|------|-----:|\n"
        f"| ユニークプロジェクト数 | **{unique}** |\n"
        f"| うち複数PCに存在（重複） | {cross_pc} |\n"
        f"| 総エントリ数（生） | {total_raw} |\n\n"
        f"## 最近の動き（直近15件）\n\n"
        f"| Updated | Path | Description |\n"
        f"|:-------:|------|-------------|\n"
        f"{recent_rows}\n\n"
        f"## プロジェクト一覧\n\n"
        f"| Path | {pc_col_header} | Updated | Description |\n"
        f"|------|{pc_col_sep}|:-------:|-------------|\n"
        f"{rows_str}\n"
    )
    (data_root / "index.md").write_text(content, encoding="utf-8")
    return unique


# ── エントリポイント ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="~/dev/ プロジェクトスキャナー")
    parser.add_argument("--merge-only", action="store_true",
                        help="スキャンをスキップして index.md だけ再生成する")
    parser.add_argument("--skip-env", action="store_true",
                        help="環境点検をスキップする（前回の点検結果は残す）")
    args = parser.parse_args()

    hostname_raw = get_stable_hostname()
    hostname = sanitize_hostname(hostname_raw)
    dev_root = (Path.home() / "dev").resolve()
    self_path = Path(__file__).resolve().parent
    data_root = self_path / "data"

    is_new_repo = ensure_data_git_repo(data_root)
    if is_new_repo:
        print("data/ を git リポジトリとして初期化しました。")
        print("プライベートリポジトリを作成後、以下を実行してください:")
        print("  cd data && git remote add origin <url> && cd ..")

    if args.merge_only:
        unique = write_merged_index(data_root)
        print(f"index.md を再生成しました ({unique} ユニークプロジェクト)")
        return

    if not dev_root.is_dir():
        print(f"Error: {dev_root} が見つかりません")
        return

    pc_root = data_root / PC_DATA_DIR / hostname
    # --skip-env のときは前回の点検結果を作り直しの前に退避する
    kept_env = {}
    if args.skip_env:
        kept_env = {name: (pc_root / name).read_bytes()
                    for name in ENV_FILES if (pc_root / name).exists()}
    shutil.rmtree(pc_root, ignore_errors=True)
    pc_root.mkdir(parents=True)
    for name, content in kept_env.items():
        (pc_root / name).write_bytes(content)

    projects = find_projects(dev_root, self_path)

    seen_keys: dict[str, int] = {}
    entries = []
    for project_path in projects:
        key = make_project_key(project_path, dev_root)
        if key in seen_keys:
            seen_keys[key] += 1
            new_key = f"{key}__{seen_keys[key]}"
            print(f"Warning: キー衝突 '{key}' → '{new_key}'", flush=True)
            key = new_key
        else:
            seen_keys[key] = 1
        try:
            entry = write_project_data(project_path, key, pc_root, dev_root)
            entries.append(entry)
        except Exception as e:
            print(f"Warning: {project_path} のスキャン中にエラー: {e}", flush=True)

    write_pc_meta(entries, pc_root, hostname, hostname_raw, dev_root)
    write_pc_entries(entries, pc_root)
    write_pc_index(entries, pc_root, hostname)

    if not args.skip_env:
        print("環境を点検しています（Windows Update の確認に数十秒かかることがあります）...", flush=True)
        write_env(collect_env(), collect_packages(), pc_root, hostname)

    unique = write_merged_index(data_root)

    print(f"Scanned {len(entries)} projects [{hostname}] → data/ (merged: {unique} unique)")
    if (pc_root / "env.json").exists():
        env = json.loads((pc_root / "env.json").read_text(encoding="utf-8"))
        print(f"\nPC環境 [{hostname}]（点検: {env['checked_at'][:16].replace('T', ' ')}）")
        for kind, os_name, last, pending in env_summary_rows(env):
            print(f"  {kind}: {os_name} / 最終更新 {last} / 更新待ち {pending}")


if __name__ == "__main__":
    main()
