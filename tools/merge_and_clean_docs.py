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

            # Skip if there are no files or only 1 file
            if len(md_files) < 2:
                continue

            # Build combined filename: name1_name2_name3.md
            combined_stem = "_".join([f.stem for f in md_files])

            # Safety guard against Windows maximum filename length limits (255 chars)
            if len(combined_stem) > 180:
                combined_stem = combined_stem[:180] + "_combined"

            combined_file_path = current_dir / f"{combined_stem}.md"

            # Merge contents from all files
            merged_sections = []
            for f in md_files:
                title = f.stem.replace("_", " ").title()
                content = f.read_text(encoding="utf-8").strip()
                merged_sections.append(f"# {title}\n\n{content}\n\n---\n")

            # 1. Write the new combined file
            combined_file_path.write_text("\n".join(merged_sections), encoding="utf-8")
            print(f"[+] Created combined file: {combined_file_path.relative_to(PROJECT_ROOT)}")

            # 2. Delete the original constituent .md files
            for f in md_files:
                if f != combined_file_path:
                    try:
                        f.unlink()
                        print(f"    [-] Deleted: {f.relative_to(PROJECT_ROOT)}")
                    except Exception as e:
                        print(f"    [!] Failed to delete {f.name}: {e}")

    print("\n[✓] Merge and cleanup complete!")

if __name__ == "__main__":
    merge_and_clean()