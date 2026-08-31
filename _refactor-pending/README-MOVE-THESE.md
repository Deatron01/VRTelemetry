# Three files this session was not allowed to write

The remote file bridge refuses to write CI workflow files and pre-commit
configuration directly — both execute code on your machine or in your CI, so
they are protected against remote writes. That is a sensible rule and I am not
going to route around it.

Move them yourself:

```powershell
cd $HOME\Desktop\VRTelemetry
mkdir .github\workflows -Force
Move-Item _refactor-pending\ci.yml               .github\workflows\ci.yml
Move-Item _refactor-pending\frontend.yml         .github\workflows\frontend.yml
Move-Item _refactor-pending\pre-commit-config.yaml .pre-commit-config.yaml
Remove-Item _refactor-pending -Recurse
```

- `ci.yml` — five jobs: repo hygiene, lint/types, clean-install on Windows and
  Ubuntu, the test matrix across Python 3.10/3.11/3.12, and a check that the
  `hardware` marker actually deselects anything.
- `frontend.yml` — `tsc --noEmit`, `oxlint`, `vite build`.
- `.pre-commit-config.yaml` — the same gates locally, plus private-key
  detection and a 500 KB added-file cap.

Everything in them was executed here before being committed. The only thing not
exercised is GitHub's own runner matrix.
