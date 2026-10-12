# Contributing

Thanks for your interest in VRTelemetry. The source is public so that it can be
read, reviewed and discussed; the project itself is proprietary (see
[LICENSE](LICENSE)).

## Issues

Bug reports and feature ideas are welcome — use the issue templates.

**Never attach real participant data.** No recordings, `.parquet` files,
`.db` files, logs from a real study, or screenshots that show a person's
details. Recordings of people are personal data and in many cases
special-category health data under the GDPR. If a bug only reproduces with a
specific file, describe its shape (columns, sampling rate, duration) or produce
a synthetic one.

Security problems go through private reporting, not issues — see
[SECURITY.md](SECURITY.md).

## Pull requests

Open an issue first so we can agree on the change before you spend time on it.
By submitting a pull request you agree to the contribution terms in section 8
of the [LICENSE](LICENSE).

Before you push, run the same gates CI runs:

```bash
pip install -e ".[dev]"
ruff check && ruff format --check
mypy
pytest -m "not hardware"
python tools/check_repo_hygiene.py
```

Conventions are described in the README's *Development* section: one ticket,
one commit, reasoning in the commit message, and docstrings that say *why*.
