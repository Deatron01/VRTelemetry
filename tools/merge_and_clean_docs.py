import os
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Folders to scan and consolidate
TARGET_DIRS = [
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "CentralServer",
    PROJECT_ROOT / "LicenseServer",
    PROJECT_ROOT / "doc",
]

IGNORE_DIRS = {
    "node_modules",
    "dist",
    "build",
    ".vite",
    "__pycache__",
    ".pytest_cache",
    "venv",
    ".git",
}


def generate_directory_tree(start_path: Path) -> str:
    """Generates a text-based tree representation of files and folders."""
    tree_lines = ["```text", f"{start_path.name}/"]

    def _walk_tree(current_path: Path, prefix: str = ""):
        try:
            items = sorted(list(current_path.iterdir()), key=lambda x: (not x.is_dir(), x.name))
        except PermissionError:
            return

        # Filter out ignored directories or redundant hidden files
        items = [
            item for item in items if item.name not in IGNORE_DIRS and not item.name.startswith(".")
        ]

        pointers = ["├── "] * (len(items) - 1) + ["└── "] if items else []
        for pointer, item in zip(pointers, items):
            if item.is_dir():
                tree_lines.append(f"{prefix}{pointer}{item.name}/")
                extension = "│   " if pointer == "├── " else "    "
                _walk_tree(item, prefix + extension)
            else:
                tree_lines.append(f"{prefix}{pointer}{item.name}")

    _walk_tree(start_path)
    tree_lines.append("```")
    return "\n".join(tree_lines)


def merge_and_clean():
    for target_dir in TARGET_DIRS:
        if not target_dir.exists():
            continue

        for root, dirs, files in os.walk(target_dir):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            current_dir = Path(root)

            # Collect all .md files in the current directory
            md_files = sorted([current_dir / f for f in files if f.endswith(".md")])

            # Skip if there are no Markdown files
            if not md_files:
                continue

            # If there is only 1 Markdown file and it is already README.md, skip
            if len(md_files) == 1 and md_files[0].name.lower() == "readme.md":
                continue

            combined_file_path = current_dir / "README.md"

            # Merge contents from all files
            merged_sections = []
            for f in md_files:
                title = f.stem.replace("_", " ").title()
                content = f.read_text(encoding="utf-8").strip()

                # Avoid duplicate "# Readme" headers if README.md is part of the merge
                if f.name.lower() != "readme.md":
                    merged_sections.append(f"# {title}\n\n{content}\n\n---\n")
                else:
                    merged_sections.append(f"{content}\n\n---\n")

            # Append the directory & file structure tree at the end
            merged_sections.append("## Folder & File Structure\n")
            merged_sections.append(
                "Here is the layout of files and subfolders contained within this path:\n"
            )
            merged_sections.append(generate_directory_tree(current_dir))

            # 1. Write the new README.md
            combined_file_path.write_text("\n".join(merged_sections), encoding="utf-8")
            print(f"[+] Created/Updated: {combined_file_path.relative_to(PROJECT_ROOT)}")

            # 2. Delete the original constituent .md files (excluding README.md)
            for f in md_files:
                if f.name.lower() != "readme.md":
                    try:
                        f.unlink()
                        print(f"    [-] Deleted: {f.relative_to(PROJECT_ROOT)}")
                    except Exception as e:
                        print(f"    [!] Failed to delete {f.name}: {e}")

    print("\n[✓] Merge and cleanup complete!")


if __name__ == "__main__":
    merge_and_clean()
