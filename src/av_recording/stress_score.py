# src/av_recording/stress_score.py
"""Deliberately not implemented. Read this before writing a line of it.

The original request (a stress/arousal score computed from a participant's
voice and speech, for a "speak in front of a virtual crowd" study design) is
plausibly an "emotion recognition system" under Article 3(39) of the EU AI
Act (Regulation (EU) 2024/1689), and Article 5(1)(f) *prohibits* such a
system in workplace and education-institution contexts, subject only to a
medical/safety exception. A corporate-communication-training-style scenario
run by an academic lab is exactly the case commentators and the Commission's
own February-2025 guidance flag as genuinely unresolved -- not a formality to
route around, and not something this codebase resolves by writing the model
anyway and hoping. A counsel opinion needs to answer, before this is built,
whether intended deployments are workplace contexts, whether "academic
research" is enough to sit outside Art. 5(1)(f) given the acknowledged
ambiguity, and whether a medical/safety framing is available.

Recording the participant's speech and transcribing it for a researcher to
read is not the same claim and is implemented (``session_recorder.py``,
``transcription.py``). Computing a score *from* that transcript/audio and
presenting it as a measurement is the specific thing gated here.

Until that opinion exists, this module holds only the shape the eventual
scorer would need to satisfy the addendum's other requirements when it is
implemented (a stated, non-clinical-sounding output; a documented validation
methodology, addendum Annex #24; a required, separate consent line, since
adding this silently to the existing P-C7 wording would mean consent was
never actually given to it -- see ``ConsentSettings.enable_av_recording``'s
docstring), so that a future implementer has to look at every requirement
here rather than rediscover them.
"""

from __future__ import annotations

from pathlib import Path

from src.av_recording.transcription import Transcript


class StressScoringNotImplementedError(NotImplementedError):
    """Raised by every path into stress scoring. See the module docstring."""


class StressScorer:
    """Placeholder for a future, legally-cleared stress/arousal score.

    Every method raises. This class exists so callers (and any future
    ``av_recordings.stress_score`` column) have one stated integration point
    rather than the feature being wired in piecemeal wherever someone finds a
    transcript.
    """

    def score(self, transcript: Transcript, media_path: Path) -> float:  # noqa: ARG002 - the signature this deliberately-unimplemented method will take
        raise StressScoringNotImplementedError(
            "Stress-score computation is not implemented pending an EU AI Act Art. 5(1)(f) "
            "opinion -- see this module's docstring."
        )
