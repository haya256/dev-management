import argparse
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
}
TREE_MAX_DEPTH = 3
README_SCAN_LINES = 30
DESCRIPTION_MAX_LEN = 120
PC_DATA_DIR = "pc-data"
PROJECTS_SUBDIR = "projects"


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
    """最終更新日 (YYYY-MM-DD)。git の最終コミット日、なければ README.md の mtime。"""
    result = subprocess.run(["git", "log", "-1", "--format=%cs"],
                            cwd=project_path, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    try:
        ts = (project_path / "README.md").stat().st_mtime
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except OSError:
        return ""


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


# ── 書き込み ──────────────────────────────────────────────────────────────────

def write_project_data(project_path: Path, key: str, pc_root: Path, dev_root: Path) -> dict:
    out_dir = pc_root / PROJECTS_SUBDIR / key
    out_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(project_path / "README.md", out_dir / "README.md")
    (out_dir / "tree.txt").write_text(generate_tree(project_path), encoding="utf-8")

    pmo_readme = project_path / "pmo" / "README.md"
    has_pmo = pmo_readme.exists()
    if has_pmo:
        pmo_out = out_dir / "pmo"
        pmo_out.mkdir(exist_ok=True)
        shutil.copy2(pmo_readme, pmo_out / "README.md")

    rel = "~/" + str(project_path.relative_to(Path.home()))
    description = extract_description(project_path / "README.md")
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
            results.append({"hostname": meta.get("hostname", subdir.name),
                            "scanned_at": meta.get("scanned_at", ""),
                            "entries": entries})
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
    content = (
        f"# Dev Projects Index (All PCs)\n\n"
        f"Last merged: {now}\n"
        f"PCs: {pc_header}\n\n"
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
    shutil.rmtree(pc_root, ignore_errors=True)
    pc_root.mkdir(parents=True)

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
    unique = write_merged_index(data_root)

    print(f"Scanned {len(entries)} projects [{hostname}] → data/ (merged: {unique} unique)")


if __name__ == "__main__":
    main()
