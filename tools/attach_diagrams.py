import os
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TARGET_DIRS = [
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "CentralServer",
    PROJECT_ROOT / "LicenseServer"
]
DOC_ROOT = PROJECT_ROOT / "doc"

IGNORE_DIRS = {
    "node_modules", "dist", "build", ".vite", 
    "__pycache__", ".pytest_cache", "venv", ".git"
}

def attach_diagrams_to_readmes():
    # 1. Gather all individual diagram files from doc/ subfolders (ignoring category READMEs)
    diagrams = {}
    if DOC_ROOT.exists():
        for diag_file in DOC_ROOT.rglob("*.md"):
            if diag_file.name.lower() == "readme.md":
                continue
            # Map the clean stem name (e.g., "backend_ocolus" or "main") to its content
            diag_key = diag_file.stem.lower()
            diagrams[diag_key] = diag_file.read_text(encoding="utf-8").strip()

    print(f"[>] Found {len(diagrams)} diagram file(s) across doc categories.")

    attached_count = 0
    # 2. Scan source folders for README.md files
    for target_dir in TARGET_DIRS:
        if not target_dir.exists():
            continue

        for root, dirs, files in os.walk(target_dir):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            current_dir = Path(root)
            readme_path = current_dir / "README.md"

            if not readme_path.exists():
                continue

            readme_content = readme_path.read_text(encoding="utf-8")
            folder_name = current_dir.name.lower()

            # Find diagrams that belong to files/modules inside this folder
            folder_diagrams_to_add = []
            
            # Check if any diagram name matches the folder name or files mentioned/present in this directory
            for diag_key, diag_content in diagrams.items():
                # Check if diagram filename matches the folder name or any file in this directory
                if diag_key in folder_name or any(diag_key in f.lower() for f in files):
                    section_title = diag_key.replace("_", " ").title()
                    block = f"\n\n## Architecture / Workflow: {section_title}\n\n{diag_content}\n"
                    if block not in readme_content:
                        folder_diagrams_to_add.append(block)

            if folder_diagrams_to_add:
                # Insert right before the Folder & File Structure tree if it exists, otherwise at the end
                if "## Folder & File Structure" in readme_content:
                    parts = readme_content.split("## Folder & File Structure")
                    new_content = parts[0].strip() + "".join(folder_diagrams_to_add) + "\n\n## Folder & File Structure" + parts[1]
                else:
                    new_content = readme_content.strip() + "".join(folder_diagrams_to_add)

                readme_path.write_text(new_content, encoding="utf-8")
                print(f"[+] Attached {len(folder_diagrams_to_add)} diagram(s) to: {readme_path.relative_to(PROJECT_ROOT)}")
                attached_count += len(folder_diagrams_to_add)

    print(f"\n[✓] Attachment complete! Embedded {attached_count} diagram(s) into folder READMEs.")

if __name__ == "__main__":
    attach_diagrams_to_readmes()