# VRTelemetry Ticket Board

**This file is the live ticketing system for the project.** GitHub Issues can't be created from the automation environment right now (repo isn't authorized for API/push access in this session — see "GitHub Sync Status" at the bottom). Until that's fixed, this board is the source of truth. Claude updates it directly, in place, every night.

**Last updated:** 2026-08-31
**Columns:** Backlog → Ready → In Progress → Review → Done

---

## 🔴 Track 1: GDPR / Legal Hardening (Highest Priority)

| ID | Title | Priority | Status | Notes |
|----|-------|----------|--------|-------|
| GDPR-01 | Enforce TLS for central server sync | P0 Critical | Backlog | `main.py`/`core/engine.py` default to `http://192.168.1.X:9000` and `http://127.0.0.1:9000`. `patient_sync_client.py` and `session_uploader.py` POST patient PII + biometric data over this in plaintext. Require `https://`, reject `http://` unless explicitly flagged for local dev, document the change. |
| GDPR-02 | Fix README's false "no external transmission" claim | P0 Critical | Backlog | README explicitly says data never leaves the local disk. It does — see GDPR-01. Update docs to accurately describe the central-sync behavior, what's transmitted, and under what consent basis, before this becomes a compliance/trust problem. |
| GDPR-03 | Encrypt `patients.db` at rest | P1 High | Backlog | SQLite file storing name, DOB, biological sex, notes as plaintext. Add SQLCipher or equivalent field-level encryption for identifying columns. |
| GDPR-04 | Persist a real consent/erasure audit trail | P1 High | Backlog | `withdraw_consent()` and `delete_patient()` only call `logger.warning()`. Add an `audit_log` table (who/what/when) so Art. 5(2) accountability isn't dependent on log-file retention. |
| GDPR-05 | Guard `hard_delete` against orphaning session references | P1 High | Backlog | `patient_manager.py::delete_patient(hard_delete=True)` deletes the row without checking `session_metadata` for references, despite the docstring assuming the caller verified it. Add the actual FK check or a `ON DELETE RESTRICT`. |
| GDPR-06 | Add access control to patient read endpoints | P1 High | Backlog | `list_patients()` / `get_patient()` have no auth/authorization layer — anything that can call them reads all un-anonymized PII. Needs at minimum a local-app auth gate before any network exposure. |
| GDPR-07 | Add self-service data export (Art. 15/20) | P2 Medium | Backlog | No endpoint found for a subject/researcher to export a patient's full record + session list in a portable format. |
| GDPR-08 | Data retention policy + auto-expiry | P2 Medium | Backlog | No mechanism to auto-delete/anonymize records past a retention window. |

---

## 📊 Track 2: Statistics & Graphs Expansion

| ID | Title | Priority | Status | Notes |
|----|-------|----------|--------|-------|
| STAT-01 | Audit existing metrics coverage vs. raw telemetry fields | P1 High | Backlog | `ScienceMetrics.ts` + `Overview.tsx`/`Physiology.tsx`/`EyeTracking.tsx`/`ResearchInsights.tsx` already exist — first pass is a gap analysis of which captured fields (pupil dilation, convergence, kinematics, hardware state) have **no** corresponding chart yet. |
| STAT-02 | Cognitive load / cyber-sickness indicator dashboard | P1 High | Backlog | README specifically calls out cyber-sickness prediction and cognitive load classification as goals (AIPostProcessor). No visible UI surfaces these derived metrics yet. |
| STAT-03 | Session comparison view (multi-session trends) | P1 High | Backlog | Compare metrics across sessions for the same patient over time — currently each session appears viewed in isolation (`SessionExplorer.tsx`). |
| STAT-04 | Export charts/report as PDF or PNG | P2 Medium | Backlog | Researchers need to pull a chart or full report out of the app for papers/records. |
| STAT-05 | Statistical summary panel (mean/std/percentiles) per metric | P2 Medium | Backlog | Raw charts exist; add a compact stats table (p50/p95, std dev, outlier count) next to each chart for at-a-glance interpretation. |
| STAT-06 | Data Quality page: extend beyond current checks | P2 Medium | Backlog | Read `DataQuality.tsx` to confirm current scope, then extend to flag sensor dropout runs, tracking-loss duration, and frame-time jitter visually. |

---

## 🎮 Track 3: 3D Heatmap Fixes

| ID | Title | Priority | Status | Notes |
|----|-------|----------|--------|-------|
| HEAT-01 | Fix beam radius scaling bug (renders as cone, not focal blob) | P0 Critical | Backlog | `SpatialViewer.tsx` ~line 293-295: `baseRadius`/`focalBoost` scale with `curDist` (distance traveled), not with proximity to `focalDist`. Beam should narrow toward a tight core at the convergence point, not widen continuously along the ray. Rework so radius depends on `depthIntensity` (already Gaussian-weighted around focal point) instead of raw distance. |
| HEAT-02 | Fix fixation detection (binocular + duration threshold) | P1 High | Backlog | Line ~316: only checks `leftLocalRot.angleTo(prevQuat) < 0.08`, initialized against an identity quaternion — first sample can misfire, and a single noisy sample counts as a fixation. Use gaze-direction (not local eye rotation alone), both eyes, and require N consecutive samples under threshold before flagging a fixation. |
| HEAT-03 | Cap voxel map size / reduce per-sample allocation | P1 High | Backlog | `voxelMap` (a `Map`) has no upper bound, and each of up to 1500 samples allocates ~9 new `THREE.Vector3` + quaternion math + 9 `addVoxelSample` calls. Long sessions risk tab freeze/crash. Pre-allocate typed arrays, reuse vector objects, and cap voxel count with LRU-style eviction of low-intensity cells. |
| HEAT-04 | Adaptive sampling instead of fixed 1500-frame cap | P2 Medium | Backlog | `step = frames.length / 1500` evenly downsamples regardless of session length — long sessions dilute fixation clusters, short ones may not need capping at all. Consider adaptive step size tied to session duration/frame rate. |
| HEAT-05 | Add unit/visual regression tests for heatmap generation | P2 Medium | Backlog | No test coverage found for `SpatialViewer.tsx`'s voxel/heatmap math — a pure function extraction (voxel binning, color mapping) would make this testable outside of React/Three.js rendering. |

---

## 📋 Reference: Full Improvement Backlog (from initial planning)

The original 30-item backlog (Backend, Frontend, Testing, Docs, Performance) from project setup is still valid and tracked in `claude/project-improvements-tracker.md` in the project. Tracks 1–3 above take priority over it based on your explicit request.

---

## 🔄 GitHub Sync Status

**Current state:** Blocked. Both the GitHub REST API and `git push` to `Deatron01/VRTelemetry` are rejected by this environment's security proxy with: *"Deatron01/VRTelemetry is not in this session's authorized repository set."* This is a session/environment-level authorization, not something controllable from chat — no tool available here can grant it.

**To unblock:** the repository needs to be added to this environment's authorized repo set. That's typically done outside the chat (environment/session configuration tied to your Claude account, separate from the personal access token you gave me). If you can find a "connect repository" / "authorize repository" option in your session or environment settings, adding `Deatron01/VRTelemetry` there should let the same automation push commits and manage Issues directly.

**Until then:** this file is the ticket system. Claude will keep it updated in place each night, and will make code changes directly in your local checkout (via the connected folder) — those changes land as local commits you can review and push yourself, or that get pushed automatically once GitHub access is unblocked.
