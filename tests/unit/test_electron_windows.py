"""The desktop app's windows become visible.

Every window is created with ``show: false`` and shown on ``ready-to-show``.
The main window registered that listener only *after* ``await loadURL(...)``
returned -- by which time a fast local page (the packaged app:// frontend) had
already fired the event, so the window existed, loaded, and never appeared.
Launching again only added a second invisible instance.

Electron cannot be run here, so this pins the source, the same way
``test_cors_policy`` pins ``electron/main.js``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _function_body(source: str, name: str) -> str:
    start = re.search(rf"function {name}\s*\(", source)
    assert start, f"{name} not found in electron/main.js"
    depth, i = 0, source.index("{", start.end())
    for j in range(i, len(source)):
        depth += {"{": 1, "}": -1}.get(source[j], 0)
        if depth == 0:
            return source[i : j + 1]
    raise AssertionError(f"unbalanced braces in {name}")


def _code(relative: str) -> str:
    source = (REPO_ROOT / relative).read_text(encoding="utf-8")
    return "\n".join(line for line in source.splitlines() if not line.strip().startswith("//"))


def test_windows_listen_for_ready_to_show_before_loading() -> None:
    code = _code("electron/main.js")

    for function in ("createWindow", "createMonitorWindow"):
        body = _function_body(code, function)
        shown = body.find("'ready-to-show'")
        loaded = body.find("loadURL(")
        assert shown != -1, f"{function} never shows its window"
        assert loaded != -1, f"{function} never loads a page"
        assert shown < loaded, (
            f"{function} registers ready-to-show after loadURL: a page that renders "
            "before loadURL resolves leaves the window hidden for good"
        )


def test_a_second_launch_focuses_the_running_app() -> None:
    """Without a single-instance lock, a second launch starts a second shell
    whose backend cannot bind 127.0.0.1:8000 and so talks to the first one's --
    and quitting the first shell then stops the backend under the second.
    """
    code = _code("electron/main.js")

    assert "app.requestSingleInstanceLock()" in code
    assert re.search(r"app\.on\(\s*'second-instance'", code), (
        "a second launch must bring the running window forward"
    )
