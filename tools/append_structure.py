import os
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Folders to scan
TARGET_DIRS = [
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "CentralServer",
    PROJECT_ROOT / "LicenseServer",
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


def append_structure():
    for target_dir in TARGET_DIRS:
        if not target_dir.exists():
            continue

        for root, dirs, files in os.walk(target_dir):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            current_dir = Path(root)
            readme_path = current_dir / "README.md"

            # Only process if a README.md already exists in this folder
            if readme_path.exists():
                content = readme_path.read_text(encoding="utf-8").strip()

                # Clean up any previously added structure section to avoid duplicates
                if "## Folder & File Structure" in content:
                    content = content.split("## Folder & File Structure")[0].strip()

                # Append the fresh tree structure
                tree_block = f"\n\n## Folder & File Structure\n\nHere is the layout of files and subfolders contained within this path:\n\n{generate_directory_tree(current_dir)}"

                updated_content = content + tree_block
                readme_path.write_text(updated_content, encoding="utf-8")
                print(f"[+] Appended folder structure to: {readme_path.relative_to(PROJECT_ROOT)}")

    print("\n[✓] Folder structure appending complete!")


if __name__ == "__main__":
    append_structure()
