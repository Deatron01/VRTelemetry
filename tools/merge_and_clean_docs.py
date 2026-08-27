import os
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Folders to scan and consolidate
TARGET_DIRS = [
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "CentralServer",
    PROJECT_ROOT / "LicenseServer",
    PROJECT_ROOT / "doc"
]

IGNORE_DIRS = {
    "node_modules", "dist", "build", ".vite", 
    "__pycache__", ".pytest_cache", "venv", ".git"
}

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