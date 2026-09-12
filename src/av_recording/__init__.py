# src/av_recording/__init__.py
"""A/V recording, transcription and (not yet) stress inference.

Speech recording, transcription & stress-inference project, Sep 2026. Records
what the participant sees (the VR runtime's compositor mirror) and hears
(their own speech) during a session, transcribes the speech locally, and
stops there -- the stress-score computation is intentionally not implemented;
see ``stress_score.py``.

Kept as its own top-level package, parallel to ``src.backends`` and
``src.eye_tracking``, rather than folded into either: it is a second
acquisition port (``IAVCaptureBackend``, alongside ``IVRBackend``) with its own
registry, its own consent gate (P-C7, not P-C3), and its own storage and
erasure paths that never reach the hub. Nothing here is imported by
``src.core.engine`` at module scope, for the same reason ``src.backends``
isn't: a machine with no capture dependencies installed (no ffmpeg, no
faster-whisper) must still be able to import the recording pipeline.
"""
