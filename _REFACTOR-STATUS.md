# What just changed in this folder

105 files have been written straight into your working tree — thirteen commits
of work, applied. P1 is now complete. Nothing is committed; it is all sitting as unstaged
changes, which is exactly what you asked for: you can read the diff before
deciding anything.

```powershell
cd $HOME\Desktop\VRTelemetry
git status
git diff --stat
git diff src/storage/database_manager.py    # the metadata fix
git diff src/central_server/server.py       # the two security fixes
```

Your working tree was verified clean before a single byte was written — all 69
modified files matched your committed `HEAD` exactly, so nothing of yours was
overwritten.

## Run it

```powershell
pip install -e ".[dev]"
pytest -m "not hardware"
```

Expect **130 passed**. Your baseline was 13 passed, 2 failed.

```powershell
ruff check          # All checks passed!
mypy                # Success: no issues found in 61 source files
python tools\check_repo_hygiene.py
```

## Four files to delete

This session can write files on your machine but not delete them — the local
shell will not start. Each of these now carries a header saying what replaced
it, so nothing is unexplained, but they should go:

```powershell
git rm pytest.ini tox.ini config.json src/utils/auto_installer.py
```

`pytest.ini` is the one that matters. pytest treats a `pytest.ini` as
authoritative even when empty, so it would override the new
`[tool.pytest.ini_options]` in `pyproject.toml`. Its contents mirror pyproject
exactly, so behaviour is identical either way — but the duplication is the
thing being removed.

## Three files to move

See `_refactor-pending\README-MOVE-THESE.md`. CI workflows and pre-commit
config are protected against remote writes, correctly.

## What is NOT done

**The history purge.** Nothing here touches git history. The subject audio and
the 100 MB archive are still reachable in the repository's history. That needs
a force-push, which needs git on your machine, which I do not have. It is
`PUSH.md` in `_refactor-p1b.zip`, and the purged history is in
`vrtelemetry-purged.bundle`.

**P2 and P3.** `src/main.py` is still 1,185 lines holding the CLI, the whole
API surface, the Pydantic schemas, raw SQL and eleven import-time singletons.
Splitting it is VRT-10 onwards, and the 63 characterisation tests now in
`tests/characterisation/` exist precisely so that split can be proven safe.

## What is done, in twelve commits

| | |
|---|---|
| VRT-2 | `.gitignore` rewritten; `build/backend.spec` tracked and its entrypoint fixed — **the packaged app could never start before this** |
| VRT-3 | patient PII no longer written to the server log; redaction filter on every sink |
| VRT-4 | cross-tenant write closed on all five data routes |
| VRT-5 | `pyproject.toml`; six undeclared runtime dependencies added; the runtime `pip install` removed |
| VRT-5.1 | import cycle broken; a dataclass import no longer drags in every VR backend |
| VRT-5.2 | `TelemetryEngine.backend` declared — the end-to-end test passes for the first time |
| VRT-7 | ruff + mypy + pre-commit; 832 auto-fixes; remaining debt scoped per file against a ticket |
| VRT-8 | CI; **found that `npm run build` fails on a clean checkout** — `@types/node` was never declared |
| VRT-22 | **session metadata persistence repaired** — 68 columns against 73 placeholders |
| VRT-9 | 63 characterisation tests covering all 29 API routes |
| VRT-6 | typed settings; 18 hardcoded paths and URLs gone; `config.example.toml` |

## Still open, deliberately

- **VRT-21** — 16 uses of naive `datetime.utcnow()` compared against stored
  ISO-8601 strings for licence expiry. A correctness bug where your hub and
  workstations need not share a timezone. Needs its own commit and test.
- **P2** — the decomposition. `src/main.py` is still 1,185 lines.

## New in VRT-6

Configuration now lives in `src/config/settings.py`. Nothing changes for you by
default — `data_root` falls back to the working directory, which is what every
old relative path effectively meant, so your existing databases are found
exactly as before. To stop behaviour depending on where the backend was
launched from:

    setx VRT_PATHS__DATA_ROOT "C:\Users\nipit\Desktop\VRTelemetry"

or copy `config.example.toml` to `config.toml` and edit it.

One deliberate behaviour change: an unconfigured central server URL is now
empty rather than defaulting to `http://127.0.0.1:9000`. That default was a
guess, and it made an unconfigured install fail with a connection error instead
of saying it was unconfigured. A characterisation test caught the change, which
is what those tests are for; it was updated on purpose, with the reasoning
written into it.
