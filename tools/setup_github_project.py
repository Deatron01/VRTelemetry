#!/usr/bin/env python3
"""
Create the VRTelemetry GitHub Projects board and seed it from PROJECT_BOARD.md.

PROJECT_BOARD.md has since been retired from the tree (it is in git history);
the GitHub Projects board this script created is now the source of truth. The
seed tickets live in this file, so it still runs without it.

Run this on a machine where the GitHub CLI is installed and logged in:

    gh auth status                       # confirm you're logged in
    gh auth refresh -s project           # one-time: add the Projects scope
    python tools/setup_github_project.py

Nothing here needs a token in a file or an environment variable -- it shells out
to `gh`, which uses the credentials already stored on this machine.

Useful flags:
    --dry-run        print what would happen, change nothing
    --skip-issues    only create/repair the project board
    --repo OWNER/NAME
    --owner OWNER    project owner (user or org); defaults to the repo owner
    --title "..."    project title
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from typing import Any

REPO = "Deatron01/VRTelemetry"
PROJECT_TITLE = "VRTelemetry Roadmap"

STATUS_OPTIONS = ["Backlog", "Ready", "In Progress", "Review", "Done"]

LABELS = [
    ("track: gdpr", "B60205", "Legal / GDPR compliance hardening"),
    ("track: stats", "1D76DB", "Statistics and graphs expansion"),
    ("track: heatmap", "0E8A16", "3D heatmap correctness and performance"),
    ("P0 Critical", "B60205", "Ship-blocking / compliance-critical"),
    ("P1 High", "D93F0B", "High priority"),
    ("P2 Medium", "FBCA04", "Medium priority"),
]

# (id, title, track label, priority label, body)
TICKETS: list[tuple[str, str, str, str, str]] = [
    (
        "GDPR-01",
        "Enforce TLS for central server sync",
        "track: gdpr",
        "P0 Critical",
        "`main.py` / `core/engine.py` default to `http://192.168.1.X:9000` and "
        "`http://127.0.0.1:9000`. `patient_sync_client.py` and `session_uploader.py` "
        "POST patient PII and biometric data over this in plaintext.\n\n"
        "**Fix:** require `https://`, reject `http://` unless explicitly flagged for "
        "local development, and document the change.",
    ),
    (
        "GDPR-02",
        'Fix README\'s false "no external transmission" claim',
        "track: gdpr",
        "P0 Critical",
        "The README explicitly states that data never leaves the local disk. It does "
        "-- see GDPR-01.\n\n"
        "**Fix:** update the docs to accurately describe the central-sync behaviour, "
        "what is transmitted, and under what consent basis, before this becomes a "
        "compliance and trust problem.",
    ),
    (
        "GDPR-03",
        "Encrypt patients.db at rest",
        "track: gdpr",
        "P1 High",
        "`patients.db` is a SQLite file storing name, date of birth, biological sex "
        "and notes as plaintext.\n\n"
        "**Fix:** add SQLCipher or equivalent field-level encryption for the "
        "identifying columns.",
    ),
    (
        "GDPR-04",
        "Persist a real consent / erasure audit trail",
        "track: gdpr",
        "P1 High",
        "`withdraw_consent()` and `delete_patient()` only call `logger.warning()`.\n\n"
        "**Fix:** add an `audit_log` table (who / what / when) so Art. 5(2) "
        "accountability does not depend on log-file retention.",
    ),
    (
        "GDPR-05",
        "Guard hard_delete against orphaning session references",
        "track: gdpr",
        "P1 High",
        "`patient_manager.py::delete_patient(hard_delete=True)` deletes the row "
        "without checking `session_metadata` for references, despite the docstring "
        "assuming the caller verified it.\n\n"
        "**Fix:** add the actual foreign-key check, or `ON DELETE RESTRICT`.",
    ),
    (
        "GDPR-06",
        "Add access control to patient read endpoints",
        "track: gdpr",
        "P1 High",
        "`list_patients()` / `get_patient()` have no authentication or authorization "
        "layer -- anything that can call them reads all un-anonymized PII.\n\n"
        "**Fix:** at minimum a local-app auth gate before any network exposure.",
    ),
    (
        "GDPR-07",
        "Add self-service data export (Art. 15/20)",
        "track: gdpr",
        "P2 Medium",
        "No endpoint exists for a subject or researcher to export a patient's full "
        "record plus session list in a portable format.",
    ),
    (
        "GDPR-08",
        "Data retention policy and auto-expiry",
        "track: gdpr",
        "P2 Medium",
        "No mechanism to auto-delete or anonymize records past a retention window.",
    ),
    (
        "STAT-01",
        "Audit existing metrics coverage vs. raw telemetry fields",
        "track: stats",
        "P1 High",
        "`ScienceMetrics.ts` plus `Overview.tsx` / `Physiology.tsx` / "
        "`EyeTracking.tsx` / `ResearchInsights.tsx` already exist.\n\n"
        "**First pass:** a gap analysis of which captured fields (pupil dilation, "
        "convergence, kinematics, hardware state) have no corresponding chart yet.",
    ),
    (
        "STAT-02",
        "Cognitive load / cyber-sickness indicator dashboard",
        "track: stats",
        "P1 High",
        "The README calls out cyber-sickness prediction and cognitive load "
        "classification as goals (AIPostProcessor), but no UI surfaces these derived "
        "metrics yet.",
    ),
    (
        "STAT-03",
        "Session comparison view (multi-session trends)",
        "track: stats",
        "P1 High",
        "Compare metrics across sessions for the same patient over time. Currently "
        "each session is viewed in isolation (`SessionExplorer.tsx`).",
    ),
    (
        "STAT-04",
        "Export charts / report as PDF or PNG",
        "track: stats",
        "P2 Medium",
        "Researchers need to pull a chart or a full report out of the app for papers and records.",
    ),
    (
        "STAT-05",
        "Statistical summary panel (mean / std / percentiles) per metric",
        "track: stats",
        "P2 Medium",
        "Raw charts exist. Add a compact stats table (p50 / p95, standard deviation, "
        "outlier count) next to each chart for at-a-glance interpretation.",
    ),
    (
        "STAT-06",
        "Data Quality page: extend beyond current checks",
        "track: stats",
        "P2 Medium",
        "Read `DataQuality.tsx` to confirm the current scope, then extend it to flag "
        "sensor dropout runs, tracking-loss duration, and frame-time jitter visually.",
    ),
    (
        "HEAT-01",
        "Fix beam radius scaling bug (renders as cone, not focal blob)",
        "track: heatmap",
        "P0 Critical",
        "`SpatialViewer.tsx` around lines 293-295: `baseRadius` / `focalBoost` scale "
        "with `curDist` (distance travelled), not with proximity to `focalDist`. The "
        "beam should narrow toward a tight core at the convergence point, not widen "
        "continuously along the ray.\n\n"
        "**Fix:** make the radius depend on `depthIntensity` (already Gaussian-"
        "weighted around the focal point) instead of raw distance.",
    ),
    (
        "HEAT-02",
        "Fix fixation detection (binocular + duration threshold)",
        "track: heatmap",
        "P1 High",
        "Around line 316, the code only checks "
        "`leftLocalRot.angleTo(prevQuat) < 0.08`, initialized against an identity "
        "quaternion -- the first sample can misfire, and a single noisy sample counts "
        "as a fixation.\n\n"
        "**Fix:** use gaze direction rather than local eye rotation alone, use both "
        "eyes, and require N consecutive samples under threshold before flagging a "
        "fixation.",
    ),
    (
        "HEAT-03",
        "Cap voxel map size and reduce per-sample allocation",
        "track: heatmap",
        "P1 High",
        "`voxelMap` (a `Map`) has no upper bound, and each of up to 1500 samples "
        "allocates roughly 9 new `THREE.Vector3` plus quaternion math and 9 "
        "`addVoxelSample` calls. Long sessions risk a tab freeze or crash.\n\n"
        "**Fix:** pre-allocate typed arrays, reuse vector objects, and cap the voxel "
        "count with LRU-style eviction of low-intensity cells.",
    ),
    (
        "HEAT-04",
        "Adaptive sampling instead of a fixed 1500-frame cap",
        "track: heatmap",
        "P2 Medium",
        "`step = frames.length / 1500` downsamples evenly regardless of session "
        "length -- long sessions dilute fixation clusters, short ones may not need "
        "capping at all.\n\n"
        "**Fix:** adaptive step size tied to session duration and frame rate.",
    ),
    (
        "HEAT-05",
        "Add unit / visual regression tests for heatmap generation",
        "track: heatmap",
        "P2 Medium",
        "No test coverage exists for `SpatialViewer.tsx`'s voxel and heatmap maths. "
        "Extracting the pure functions (voxel binning, colour mapping) would make "
        "this testable outside React and Three.js rendering.",
    ),
]

DRY_RUN = False


# --------------------------------------------------------------------------- #
# gh helpers
# --------------------------------------------------------------------------- #


def run(args: list[str], *, check: bool = True, mutating: bool = False) -> str:
    """Run a gh command and return stdout."""
    if mutating and DRY_RUN:
        print(f"    [dry-run] {' '.join(args)}")
        return ""
    proc = subprocess.run(args, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(args)}\n"
            f"stdout: {proc.stdout.strip()}\n"
            f"stderr: {proc.stderr.strip()}"
        )
    return proc.stdout.strip()


def run_json(args: list[str]) -> Any:
    out = run(args)
    return json.loads(out) if out else None


def preflight(owner: str) -> None:
    if shutil.which("gh") is None:
        sys.exit(
            "gh (GitHub CLI) is not installed or not on PATH.\n"
            "Install it from https://cli.github.com/ and run `gh auth login`."
        )

    proc = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit("gh is not logged in. Run:\n    gh auth login\n    gh auth refresh -s project")

    status = proc.stdout + proc.stderr
    if "project" not in status:
        print(
            "WARNING: the 'project' OAuth scope does not appear in `gh auth status`.\n"
            "         Creating a Projects board will fail without it. Run:\n"
            "             gh auth refresh -s project\n"
        )

    print(f"  gh authenticated. Target repo: {REPO}, project owner: {owner}")


# --------------------------------------------------------------------------- #
# steps
# --------------------------------------------------------------------------- #


def ensure_labels() -> None:
    print("\n[1/6] Labels")
    for name, color, desc in LABELS:
        run(
            [
                "gh",
                "label",
                "create",
                name,
                "--repo",
                REPO,
                "--color",
                color,
                "--description",
                desc,
                "--force",
            ],
            mutating=True,
        )
        print(f"    ok  {name}")


def existing_by_ticket_id() -> dict[str, str]:
    """Map of ticket id (e.g. 'GDPR-01') -> issue url.

    Matches on the ticket ID appearing anywhere in the title, so all of
    '[GDPR-01] Foo', 'GDPR-01: Foo' and 'GDPR-01 Foo' count as the same
    ticket. Matching on the full title instead once created 19 duplicates.
    """
    items = (
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
                "title,url",
            ]
        )
        or []
    )

    found: dict[str, str] = {}
    for issue in items:
        title = issue["title"].upper()
        for ticket_id, *_ in TICKETS:
            if ticket_id in title and ticket_id not in found:
                found[ticket_id] = issue["url"]
    return found


def ticket_urls_in_order() -> list[str]:
    """URLs of the 19 tracked tickets only -- never every issue in the repo."""
    found = existing_by_ticket_id()
    return [found[t[0]] for t in TICKETS if t[0] in found]


def create_issues() -> list[str]:
    print("\n[2/6] Issues")
    existing = existing_by_ticket_id()
    urls: list[str] = []

    for ticket_id, title, track, priority, body in TICKETS:
        full_title = f"[{ticket_id}] {title}"
        if ticket_id in existing:
            print(f"    skip  {ticket_id}  (already exists: {existing[ticket_id]})")
            urls.append(existing[ticket_id])
            continue

        full_body = f"{body}\n\n---\n_Ticket `{ticket_id}`, imported from `PROJECT_BOARD.md`._"
        url = run(
            [
                "gh",
                "issue",
                "create",
                "--repo",
                REPO,
                "--title",
                full_title,
                "--body",
                full_body,
                "--label",
                track,
                "--label",
                priority,
            ],
            mutating=True,
        )
        url = url.splitlines()[-1] if url else ""
        print(f"    new   {full_title}")
        if url:
            urls.append(url)

    return urls


def find_or_create_project(owner: str, title: str) -> dict[str, Any]:
    print("\n[3/6] Project board")
    projects = (
        run_json(["gh", "project", "list", "--owner", owner, "--format", "json", "--limit", "100"])
        or {}
    )
    for p in projects.get("projects", []):
        if p.get("title") == title:
            print(f"    found existing project #{p['number']} ({title})")
            return p

    if DRY_RUN:
        print(f"    [dry-run] would create project '{title}' under {owner}")
        return {"number": 0, "id": "DRYRUN", "title": title}

    created = run_json(
        [
            "gh",
            "project",
            "create",
            "--owner",
            owner,
            "--title",
            title,
            "--format",
            "json",
        ]
    )
    print(f"    created project #{created['number']} ({title})")
    return created


def configure_status_field(owner: str, number: int) -> None:
    """Rename the default Status options to our five columns."""
    print("\n[4/6] Status columns")
    if DRY_RUN:
        print(f"    [dry-run] would set columns to: {', '.join(STATUS_OPTIONS)}")
        return

    fields = (
        run_json(
            [
                "gh",
                "project",
                "field-list",
                str(number),
                "--owner",
                owner,
                "--format",
                "json",
                "--limit",
                "50",
            ]
        )
        or {}
    )
    status = next((f for f in fields.get("fields", []) if f.get("name") == "Status"), None)
    if not status:
        print("    no Status field found -- skipping")
        return

    options = ", ".join(f'{{name: "{o}", color: GRAY, description: ""}}' for o in STATUS_OPTIONS)
    field_id = status["id"]
    query = (
        f'mutation {{ updateProjectV2Field(input: {{fieldId: "{field_id}", '
        f"singleSelectOptions: [{options}]}}) {{ projectV2Field {{ "
        "... on ProjectV2SingleSelectField { id options { id name } } } } }"
    )
    try:
        run(["gh", "api", "graphql", "-f", f"query={query}"], mutating=True)
        print(f"    columns set to: {', '.join(STATUS_OPTIONS)}")
    except RuntimeError as exc:
        first_line = str(exc).splitlines()[0]
        print(f"    could not rewrite Status options: {first_line}")
        print("    -> set them by hand in the Projects UI; everything else is done.")


def add_items(owner: str, number: int, urls: list[str]) -> None:
    print("\n[5/6] Adding issues to the board")
    for url in urls:
        try:
            run(
                ["gh", "project", "item-add", str(number), "--owner", owner, "--url", url],
                mutating=True,
            )
            print(f"    added {url}")
        except RuntimeError as exc:
            print(f"    FAILED {url}: {exc}")


def set_initial_status(owner: str, number: int, project_id: str, status: str) -> None:
    """Give every item on the board a Status, so none sit in 'No Status'."""
    print(f"\n[6/6] Setting Status = {status} on items that have none")
    if DRY_RUN:
        print(f"    [dry-run] would set every statusless item to {status}")
        return

    fields = (
        run_json(
            [
                "gh",
                "project",
                "field-list",
                str(number),
                "--owner",
                owner,
                "--format",
                "json",
                "--limit",
                "50",
            ]
        )
        or {}
    )
    field = next((f for f in fields.get("fields", []) if f.get("name") == "Status"), None)
    if not field:
        print("    no Status field found -- skipping")
        return

    option = next((o for o in field.get("options", []) if o.get("name") == status), None)
    if not option:
        names = ", ".join(o.get("name", "?") for o in field.get("options", []))
        print(f"    no '{status}' option (have: {names}) -- skipping")
        return

    items = (
        run_json(
            [
                "gh",
                "project",
                "item-list",
                str(number),
                "--owner",
                owner,
                "--format",
                "json",
                "--limit",
                "200",
            ]
        )
        or {}
    )

    done = 0
    for item in items.get("items", []):
        if item.get("status"):
            continue
        try:
            run(
                [
                    "gh",
                    "project",
                    "item-edit",
                    "--id",
                    item["id"],
                    "--project-id",
                    project_id,
                    "--field-id",
                    field["id"],
                    "--single-select-option-id",
                    option["id"],
                ],
                mutating=True,
            )
            done += 1
        except RuntimeError as exc:
            title = item.get("title", item.get("id", "?"))
            print(f"    FAILED {title}: {str(exc).splitlines()[0]}")

    print(f"    set {done} item(s) to {status}")


# --------------------------------------------------------------------------- #


def main() -> None:
    global DRY_RUN, REPO, PROJECT_TITLE

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=REPO, help="owner/name of the repository")
    ap.add_argument("--owner", default=None, help="project owner (defaults to repo owner)")
    ap.add_argument("--title", default=PROJECT_TITLE, help="project board title")
    ap.add_argument("--dry-run", action="store_true", help="show actions, change nothing")
    ap.add_argument("--skip-issues", action="store_true", help="only set up the board")
    ap.add_argument(
        "--set-status",
        default="Backlog",
        help="column to drop statusless items into (empty string to skip)",
    )
    args = ap.parse_args()

    DRY_RUN = args.dry_run
    REPO = args.repo
    PROJECT_TITLE = args.title
    owner = args.owner or REPO.split("/")[0]

    print("VRTelemetry -> GitHub Projects setup")
    if DRY_RUN:
        print("*** DRY RUN -- nothing will be created ***")
    preflight(owner)

    ensure_labels()

    if args.skip_issues:
        print("\n[2/6] Issues -- skipped (--skip-issues)")
        # Only the 19 tracked tickets. Using every issue in the repo here
        # once dragged 39 unrelated items onto the board.
        urls = ticket_urls_in_order()
        print(f"    board will use the {len(urls)} tracked ticket(s) already on the repo")
    else:
        urls = create_issues()

    project = find_or_create_project(owner, PROJECT_TITLE)
    number = int(project.get("number", 0))

    if number:
        configure_status_field(owner, number)
        add_items(owner, number, urls)
        if args.set_status:
            set_initial_status(owner, number, project.get("id", ""), args.set_status)
        print(
            f"\nDone. Board: https://github.com/users/{owner}/projects/{number}"
            "\n(If your owner is an organization, the URL is "
            f"https://github.com/orgs/{owner}/projects/{number} instead.)"
        )
    else:
        print("\nDry run complete.")


if __name__ == "__main__":
    main()
