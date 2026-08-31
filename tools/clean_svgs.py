from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOC_ROOT = PROJECT_ROOT / "doc"


def remove_svgs():
    if not DOC_ROOT.exists():
        print(f"[!] The 'doc' folder does not exist at: {DOC_ROOT}")
        return

    deleted_count = 0
    print(f"[>] Scanning '{DOC_ROOT.relative_to(PROJECT_ROOT)}' for SVG files...")

    # Recursively find all .svg files
    for svg_file in DOC_ROOT.rglob("*.svg"):
        if svg_file.is_file():
            try:
                svg_file.unlink()
                print(f"    [-] Deleted: {svg_file.relative_to(PROJECT_ROOT)}")
                deleted_count += 1
            except Exception as e:
                print(f"    [!] Failed to delete {svg_file.name}: {e}")

    print(f"\n[✓] Cleanup complete! Successfully removed {deleted_count} SVG file(s).")


if __name__ == "__main__":
    remove_svgs()
