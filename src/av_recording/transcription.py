# src/av_recording/transcription.py
"""Local speech-to-text transcription of a captured session recording.

Self-hosted deliberately (addendum, Section 2.3): sending Art. 9 audio to a
third-party cloud ASR API needs that vendor's terms confirmed to disclaim
training use on the audio first, and no such review has happened for this
feature. faster-whisper runs entirely on the workstation -- the audio never
leaves it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.utils.clock import utc_now_iso
from src.utils.logger import logger


class TranscriptionUnavailableError(RuntimeError):
    """faster-whisper is not installed, or transcription itself failed.

    Never fatal to the session: the video was already captured and kept (see
    ``SessionRecorder``) regardless of whether it could be transcribed.
    """


@dataclass(frozen=True)
class TranscriptSegment:
    start_sec: float
    end_sec: float
    text: str


@dataclass(frozen=True)
class Transcript:
    engine: str
    language: str | None
    segments: tuple[TranscriptSegment, ...]
    generated_at_utc: str = field(default_factory=utc_now_iso)

    @property
    def full_text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments).strip()

    def as_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "language": self.language,
            "generated_at_utc": self.generated_at_utc,
            "full_text": self.full_text,
            "segments": [
                {"start_sec": s.start_sec, "end_sec": s.end_sec, "text": s.text}
                for s in self.segments
            ],
        }

    def write_json(self, path: Path) -> None:
        """Write this transcript to ``path`` as the JSON file the erasure glob targets."""
        path.write_text(json.dumps(self.as_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


class WhisperTranscriber:
    """Transcribes a video/audio file's speech track with faster-whisper.

    Args:
        model_size: e.g. "tiny", "base", "small". Larger is slower and more
            accurate; "base" is a reasonable default on a workstation with no
            dedicated inference GPU.
        language: A language code to force, or None to auto-detect.
    """

    #: Substrings a GPU/CUDA-runtime failure includes -- as opposed to a
    #: genuine media/decoding problem, which must still surface as an error
    #: rather than being retried forever.
    _GPU_RUNTIME_FAILURE_MARKERS = ("cublas", "cudnn", "libcu", "cuda")

    def __init__(self, model_size: str = "base", language: str | None = None) -> None:
        self.model_size = model_size
        self.language = language
        self._model: Any = None
        #: "auto" first (GPU when CTranslate2 detects one), demoted to "cpu"
        #: for the rest of this transcriber's life the first time "auto"
        #: turns out not to actually work -- see ``transcribe``.
        self._device = "auto"

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscriptionUnavailableError(
                "faster-whisper is not installed. `pip install faster-whisper` to enable "
                "transcription -- the recording is still captured and kept without a "
                "transcript until this is installed and the session is (re-)transcribed."
            ) from exc
        logger.info(
            f"Loading faster-whisper model {self.model_size!r} on device={self._device!r} "
            "(first use is slow)..."
        )
        self._model = WhisperModel(self.model_size, device=self._device, compute_type="int8")
        return self._model

    def transcribe(self, media_path: Path) -> Transcript:
        """Transcribe ``media_path``'s audio track (ffmpeg reads it directly from the mp4).

        Raises:
            TranscriptionUnavailableError: faster-whisper is not installed, or
                the media could not be decoded/transcribed even on CPU.
        """
        model = self._load_model()
        info = None
        try:
            segments_iter, info = model.transcribe(str(media_path), language=self.language)
            segments = tuple(
                TranscriptSegment(start_sec=s.start, end_sec=s.end, text=s.text)
                for s in segments_iter
            )
        except Exception as exc:
            if isinstance(exc, IndexError) and "tuple index out of range" in str(exc).lower():
                # faster-whisper raises this when the audio track is missing or completely silent.
                # This is a normal state (e.g. video-only fallback), so return an empty transcript.
                logger.info(
                    f"No audio found or completely silent in {media_path.name}; skipping transcription."
                )
                detected_language = self.language
                if info is not None and hasattr(info, "language"):
                    detected_language = info.language or self.language
                return Transcript(
                    engine=f"faster-whisper:{self.model_size}",
                    language=detected_language,
                    segments=(),
                )

            if self._device != "cpu" and self._looks_like_a_gpu_runtime_failure(exc):
                # CTranslate2's device="auto" only *detects* a GPU at model
                # construction; it does not verify the CUDA/cuBLAS/cuDNN
                # runtime underneath actually works, so the constructor
                # succeeds and this is where a workstation with a GPU but no
                # CUDA toolkit installed (the ordinary state of a
                # researcher's machine never set up for ML work -- observed
                # for real on VRT's own test machine) first fails. Retry once
                # on CPU (``int8`` is already the fast, low-memory
                # CPU-friendly mode faster-whisper's own docs recommend, so
                # this is a real fallback, not a degraded one) rather than
                # making transcription unavailable on a perfectly capable
                # machine.
                logger.warning(
                    f"faster-whisper failed on device={self._device!r} ({exc}); retrying on "
                    "CPU. This is expected on a machine with a GPU but no CUDA/cuBLAS/cuDNN "
                    "runtime installed."
                )
                self._device = "cpu"
                self._model = None
                return self.transcribe(media_path)
            raise TranscriptionUnavailableError(
                f"Transcription failed for {media_path.name}: {exc}"
            ) from exc
        detected_language = getattr(info, "language", None) or self.language
        return Transcript(
            engine=f"faster-whisper:{self.model_size}",
            language=detected_language,
            segments=segments,
        )

    @classmethod
    def _looks_like_a_gpu_runtime_failure(cls, exc: Exception) -> bool:
        text = str(exc).lower()
        return any(marker in text for marker in cls._GPU_RUNTIME_FAILURE_MARKERS)
