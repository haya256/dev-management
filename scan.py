import os
import re
import shutil
from datetime import datetime
from pathlib import Path

SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", "venv", ".venv",
    "dist", "build", "target", ".idea", ".vscode",
}
TREE_MAX_DEPTH = 3
README_SCAN_LINES = 30
DESCRIPTION_MAX_LEN = 120


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
        # Strip inline Markdown
        cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", stripped)
        cleaned = re.sub(r"[*_`~]+", "", cleaned)
        cleaned = cleaned.strip()
        if cleaned:
            if len(cleaned) > DESCRIPTION_MAX_LEN:
                cleaned = cleaned[:DESCRIPTION_MAX_LEN - 1] + "…"
            return cleaned

    return "*(no description)*"


def write_project_data(project_path: Path, key: str, data_root: Path) -> dict:
    out_dir = data_root / key
    out_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(project_path / "README.md", out_dir / "README.md")

    tree_text = generate_tree(project_path)
    (out_dir / "tree.txt").write_text(tree_text, encoding="utf-8")

    description = extract_description(project_path / "README.md")
    rel = "~/" + str(project_path.relative_to(Path.home()))
    return {"key": key, "path": rel, "description": description}


def write_index(entries: list[dict], data_root: Path):
    entries = sorted(entries, key=lambda e: e["key"])
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = "\n".join(
        f"| {e['key']} | {e['path']} | {e['description']} |"
        for e in entries
    )
    content = (
        f"# Dev Projects Index\n\n"
        f"Generated: {now}  |  Found: {len(entries)} projects\n\n"
        f"| Project Key | Path | Description |\n"
        f"|-------------|------|-------------|\n"
        f"{rows}\n"
    )
    (data_root / "index.md").write_text(content, encoding="utf-8")


def main():
    dev_root = (Path.home() / "dev").resolve()
    self_path = Path(__file__).resolve().parent
    data_root = self_path / "data"

    if not dev_root.is_dir():
        print(f"Error: {dev_root} が見つかりません")
        return

    if data_root.exists():
        shutil.rmtree(data_root)
    data_root.mkdir()

    projects = find_projects(dev_root, self_path)

    # キー衝突チェック
    seen_keys: dict[str, int] = {}
    entries = []
    for project_path in projects:
        key = make_project_key(project_path, dev_root)
        if key in seen_keys:
            seen_keys[key] += 1
            new_key = f"{key}__{seen_keys[key]}"
            print(f"Warning: キー衝突 '{key}' → '{new_key}' として保存", flush=True)
            key = new_key
        else:
            seen_keys[key] = 1
        try:
            entry = write_project_data(project_path, key, data_root)
            entries.append(entry)
        except Exception as e:
            print(f"Warning: {project_path} のスキャン中にエラー: {e}", flush=True)

    write_index(entries, data_root)
    print(f"Scanned {len(entries)} projects → data/")


if __name__ == "__main__":
    main()
