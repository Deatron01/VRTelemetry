#!/usr/bin/env python3
"""
Close the duplicate VRTelemetry tickets and tidy the Roadmap board.

Background: two sets of the same 19 tickets exist on the repo.

  * The ORIGINALS (#1-#19) use the title form "GDPR-01: Title". They carry
    milestones, the GDPR / P0-Critical / compliance labels, action-item
    checklists, and are already on the other project boards. These are kept.
  * The DUPLICATES use the title form "[GDPR-01] Title". They were created by
    an earlier version of setup_github_project.py whose duplicate check
    compared full titles instead of ticket IDs. These are closed.

What this does, per ticket ID:
  1. finds both issues,
  2. comments on the duplicate pointing at the original,
  3. closes the duplicate as "not planned",
  4. removes the duplicate from the Roadmap project board.

Nothing is deleted -- closing is reversible. If you would rather delete the
duplicate issues outright, do that yourself with `gh issue delete <n>`; it is
irreversible, so this script will not do it for you.

Also removes any board item that is not one of the 19 tracked tickets
(--prune-board), since --skip-issues previously dragged every repo issue on.

Usage:
    python tools/cleanup_duplicate_issues.py --dry-run     # look first
    python tools/cleanup_duplicate_issues.py
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from typing import Any

REPO = "Deatron01/VRTelemetry"
PROJECT_OWNER = "Deatron01"
PROJECT_NUMBER = 4

TICKET_IDS = (
    [f"GDPR-{i:02d}" for i in range(1, 9)]
    + [f"STAT-{i:02d}" for i in range(1, 7)]
    + [f"HEAT-{i:02d}" for i in range(1, 6)]
)

# "[GDPR-01] ..." -> the duplicate set. "GDPR-01: ..." -> the originals.
_TICKET_ALT = "|".join(TICKET_IDS)
DUPLICATE_RE = re.compile(rf"^\[\s*({_TICKET_ALT})\s*\]", re.I)
ORIGINAL_RE = re.compile(rf"^\s*({_TICKET_ALT})\s*[:\-]", re.I)

DRY_RUN = False


def run(args: list[str], *, check: bool = True, mutating: bool = False) -> str:
    if mutating and DRY_RUN:
        print(f"      [dry-run] {' '.join(args)}")
        return ""
    proc = subprocess.run(args, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(args)}\n"
            f"stdout: {proc.stdout.strip()}\nstderr: {proc.stderr.strip()}"
        )
    return proc.stdout.strip()


def run_json(args: list[str]) -> Any:
    out = run(args)
    return json.loads(out) if out else None


def classify() -> tuple[dict[str, dict], dict[str, dict]]:
    """Return (originals, duplicates), each ticket_id -> issue dict."""
    issues = (
        run_json(
            [
                "gh",
                "issue",
                "list",
                "--repo",
                REPO,
                "--state",
                "all",
                "--limit",
                "500",
                "--json",
                "number,title,url,state",
            ]
        )
        or []
    )

    originals: dict[str, dict] = {}
    duplicates: dict[str, dict] = {}

    for issue in issues:
        title = issue["title"]
        m = DUPLICATE_RE.match(title)
        if m:
            duplicates.setdefault(m.group(1).upper(), issue)
            continue
        m = ORIGINAL_RE.match(title)
        if m:
            originals.setdefault(m.group(1).upper(), issue)

    return originals, duplicates


def close_duplicates(originals: dict[str, dict], duplicates: dict[str, dict]) -> list[int]:
    print("\n[1/2] Closing duplicate issues")
    closed: list[int] = []

    for ticket_id in TICKET_IDS:
        dup = duplicates.get(ticket_id)
        orig = originals.get(ticket_id)

        if not dup:
            print(f"    {ticket_id}: no duplicate found -- nothing to do")
            continue
        if not orig:
            print(
                f"    {ticket_id}: WARNING duplicate #{dup['number']} found but no "
                f"original -- leaving it open"
            )
            continue
        if dup["state"].upper() == "CLOSED":
            print(f"    {ticket_id}: #{dup['number']} already closed")
            closed.append(dup["number"])
            continue

        comment = (
            f"Duplicate of #{orig['number']}, which is the original ticket "
            f"(it carries the milestone, labels and action items). Closing this "
            f"one; work tracked on #{orig['number']}."
        )
        run(
            ["gh", "issue", "comment", str(dup["number"]), "--repo", REPO, "--body", comment],
            mutating=True,
        )
        run(
            ["gh", "issue", "close", str(dup["number"]), "--repo", REPO, "--reason", "not planned"],
            mutating=True,
        )
        print(f"    {ticket_id}: closed #{dup['number']} (dupe of #{orig['number']})")
        closed.append(dup["number"])

    return closed


def prune_board(keep_numbers: set[int]) -> None:
    print("\n[2/2] Pruning the Roadmap board")

    project = (
        run_json(
            [
                "gh",
                "project",
                "view",
                str(PROJECT_NUMBER),
                "--owner",
                PROJECT_OWNER,
                "--format",
                "json",
            ]
        )
        or {}
    )
    project_id = project.get("id")
    if not project_id:
        print("    could not resolve the project id -- skipping")
        return

    items = (
        run_json(
            [
                "gh",
                "project",
                "item-list",
                str(PROJECT_NUMBER),
                "--owner",
                PROJECT_OWNER,
                "--format",
                "json",
                "--limit",
                "300",
            ]
        )
        or {}
    )

    removed = 0
    for item in items.get("items", []):
        number = item.get("content", {}).get("number")
        if number is None or number in keep_numbers:
            continue
        title = item.get("title", f"#{number}")
        try:
            run(
                [
                    "gh",
                    "project",
                    "item-delete",
                    str(PROJECT_NUMBER),
                    "--owner",
                    PROJECT_OWNER,
                    "--id",
                    item["id"],
                ],
                mutating=True,
            )
            print(f"    removed #{number}  {title}")
            removed += 1
        except RuntimeError as exc:
            print(f"    FAILED #{number}: {str(exc).splitlines()[0]}")

    print(f"    removed {removed} item(s); {len(keep_numbers)} tracked ticket(s) kept")


def main() -> None:
    global DRY_RUN

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="show actions, change nothing")
    ap.add_argument("--no-prune-board", action="store_true", help="leave every board item in place")
    args = ap.parse_args()
    DRY_RUN = args.dry_run

    if shutil.which("gh") is None:
        sys.exit("gh is not on PATH.")

    print("VRTelemetry duplicate cleanup")
    if DRY_RUN:
        print("*** DRY RUN -- nothing will change ***")

    originals, duplicates = classify()
    print(f"\n  originals found:  {len(originals)}/19")
    print(f"  duplicates found: {len(duplicates)}/19")

    if not duplicates:
        print("\nNothing to clean up.")
        return

    close_duplicates(originals, duplicates)

    if not args.no_prune_board:
        keep = {o["number"] for o in originals.values()}
        prune_board(keep)

    print(f"\nDone. Board: https://github.com/users/{PROJECT_OWNER}/projects/{PROJECT_NUMBER}")


if __name__ == "__main__":
    main()
