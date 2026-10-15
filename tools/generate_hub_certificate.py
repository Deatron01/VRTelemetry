#!/usr/bin/env python3
"""Create a TLS certificate for a VRTelemetry hub on a local network (GDPR-01).

The implementation is :mod:`src.central_server.certificates`, which moved into
the package so the frozen hub can run it. This path stays because the README,
SECURITY.md and the hub's own refusal message tell people to run it.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Run as a script from a checkout, where `src` is not installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.central_server.certificates import DEFAULT_DAYS, generate, main

__all__ = ["DEFAULT_DAYS", "generate", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
