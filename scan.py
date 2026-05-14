import argparse
import json
import os
import re
import shutil
import socket
import subprocess
from datetime import datetime
from pathlib import Path

SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", "venv", ".venv",
    "dist", "build", "target", ".idea", ".vscode",
}
TREE_MAX_DEPTH = 3
README_SCAN_LINES = 30
DESCRIPTION_MAX_LEN = 120
PC_DATA_DIR = "pc-data"
PROJECTS_SUBDIR = "projects"


# ── ヘルパー ──────────────────────────────────────────────────────────────────

def sanitize_hostname(raw: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", raw)


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
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        if "README.md" in files:
            results.append(current)
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

    rel = "~/" + str(project_path.relative_to(Path.home()))
    has_pmo = (project_path / "pmo").is_dir()
    description = extract_description(project_path / "README.md")
    return {"key": key, "path": rel, "has_pmo": has_pmo, "description": description}


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
        f"| {e['key']} | {e['path']} | {'YES' if e['has_pmo'] else ''} | {e['description']} |"
        for e in sorted(entries, key=lambda e: e["key"])
    )
    content = (
        f"# Dev Projects Index — {hostname}\n\n"
        f"Scanned: {now}  |  Projects: {len(entries)}\n\n"
        f"| Project Key | Path | Main | Description |\n"
        f"|-------------|------|:----:|-------------|\n"
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


def write_merged_index(data_root: Path):
    pc_data = discover_pc_data(data_root)
    if not pc_data:
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pc_header = "  ".join(
        f"{pc['hostname']} ({pc['scanned_at'][:16].replace('T', ' ')})"
        for pc in pc_data
    )

    all_rows = []
    for pc in pc_data:
        for e in pc["entries"]:
            all_rows.append({
                "pc": pc["hostname"],
                "key": e["key"],
                "path": e["path"],
                "has_pmo": e.get("has_pmo", False),
                "description": e.get("description", ""),
            })
    all_rows.sort(key=lambda r: (r["key"], r["pc"]))

    rows = "\n".join(
        f"| {r['pc']} | {r['key']} | {r['path']} | {'YES' if r['has_pmo'] else ''} | {r['description']} |"
        for r in all_rows
    )
    total = len(all_rows)
    content = (
        f"# Dev Projects Index (All PCs)\n\n"
        f"Last merged: {now}\n"
        f"PCs: {pc_header}\n\n"
        f"| PC | Project Key | Path | Main | Description |\n"
        f"|----|-------------|------|:----:|-------------|\n"
        f"{rows}\n"
    )
    (data_root / "index.md").write_text(content, encoding="utf-8")
    return total


# ── エントリポイント ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="~/dev/ プロジェクトスキャナー")
    parser.add_argument("--merge-only", action="store_true",
                        help="スキャンをスキップして index.md だけ再生成する")
    args = parser.parse_args()

    hostname_raw = socket.gethostname()
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
        total = write_merged_index(data_root)
        print(f"index.md を再生成しました ({total} エントリ)")
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
    total = write_merged_index(data_root)

    print(f"Scanned {len(entries)} projects [{hostname}] → data/")


if __name__ == "__main__":
    main()
