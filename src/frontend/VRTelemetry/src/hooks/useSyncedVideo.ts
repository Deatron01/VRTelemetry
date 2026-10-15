import { useEffect, useMemo, useState } from 'react';
import { useTelemetryStore } from '../store/useTelemetryStore';

interface AvRecordingInfo {
  started_at_utc: string | null;
  has_video: boolean;
  video_deleted_at_utc: string | null;
  failure_reason: string | null;
}

function parseNaiveUtcMs(value: string | null | undefined): number | null {
  if (!value) return null;
  const iso = value.includes(' ') ? value.replace(' ', 'T') : value;
  const withZone = /[zZ]|[+-]\d{2}:\d{2}$/.test(iso) ? iso : `${iso}Z`;
  const ms = Date.parse(withZone);
  return Number.isNaN(ms) ? null : ms;
}

const DRIFT_TOLERANCE_PLAYING_SEC = 0.35;
const DRIFT_TOLERANCE_PAUSED_SEC = 0.05;

/**
 * Custom hook to fetch session video info, create a video element,
 * and synchronize its playback with the global telemetry store.
 */
export function useSyncedVideo() {
  const metadata = useTelemetryStore((state) => state.metadata);
  const sessionId = metadata?.session_id;

  const [avInfo, setAvInfo] = useState<AvRecordingInfo | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [videoError, setVideoError] = useState<string | null>(null);
  const [videoElement, setVideoElement] = useState<HTMLVideoElement | null>(null);
  const [videoAspect, setVideoAspect] = useState<number>(16 / 9);

  useEffect(() => {
    setAvInfo(null);
    setVideoError(null);
    setVideoElement(null);
    setVideoAspect(16 / 9);
    if (!sessionId) {
      setIsLoading(false);
      return;
    }
    let cancelled = false;
    let vid: HTMLVideoElement | null = null;
    setIsLoading(true);
    fetch(`http://localhost:8000/api/sessions/${sessionId}/av-recording`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled) {
            setAvInfo(data);
            if (data?.has_video) {
                vid = document.createElement('video');
                vid.src = `http://localhost:8000/api/sessions/${sessionId}/av-recording/video`;
                vid.crossOrigin = 'anonymous';
                vid.playsInline = true;
                vid.muted = true; // Mute for 3D to avoid double audio if the 2D panel is also playing

                vid.onloadedmetadata = () => {
                    if (!cancelled && vid) {
                        setVideoAspect(vid.videoWidth / Math.max(vid.videoHeight, 1));
                    }
                };

                vid.onerror = () => {
                    if (!cancelled) setVideoError('Could not load the recorded video.');
                };

                // Append to DOM to force Chrome to decode it (so THREE.VideoTexture can read frames)
                vid.style.position = 'absolute';
                vid.style.opacity = '0';
                vid.style.pointerEvents = 'none';
                vid.style.width = '1px';
                vid.style.height = '1px';
                document.body.appendChild(vid);

                setVideoElement(vid);
            }
        }
      })
      .catch(() => {
        if (!cancelled) setAvInfo(null);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
      if (vid) {
        vid.removeAttribute('src');
        vid.load();
        if (vid.parentNode) {
            vid.parentNode.removeChild(vid);
        }
      }
    };
  }, [sessionId]);

  const offsetSec = useMemo(() => {
    const sessionStartMs = parseNaiveUtcMs(metadata?.start_timestamp_utc);
    const videoStartMs = parseNaiveUtcMs(avInfo?.started_at_utc);
    if (sessionStartMs === null || videoStartMs === null) return 0;
    return (videoStartMs - sessionStartMs) / 1000;
  }, [metadata?.start_timestamp_utc, avInfo?.started_at_utc]);

  useEffect(() => {
    if (!videoElement || !avInfo?.has_video) return;

    let raf = 0;
    const tick = () => {
      const state = useTelemetryStore.getState();
      const { frames, currentFrameIdx, isPlaying, playbackSpeed } = state;
      const frame = frames[currentFrameIdx];

      if (frame && frames.length > 1 && videoElement.readyState >= 1) {
        const elapsedSec = (frame.timestamp_ns - frames[0].timestamp_ns) / 1e9;
        const rawTargetSec = elapsedSec - offsetSec;
        const targetSec = Number.isFinite(videoElement.duration)
          ? Math.min(Math.max(rawTargetSec, 0), videoElement.duration)
          : Math.max(rawTargetSec, 0);

        if (isPlaying) {
          if (videoElement.paused) videoElement.play().catch(() => {});
          if (Math.abs(videoElement.playbackRate - playbackSpeed) > 0.001) {
            videoElement.playbackRate = playbackSpeed;
          }
          if (Math.abs(videoElement.currentTime - targetSec) > DRIFT_TOLERANCE_PLAYING_SEC) {
            videoElement.currentTime = targetSec;
          }
        } else {
          if (!videoElement.paused) videoElement.pause();
          if (Math.abs(videoElement.currentTime - targetSec) > DRIFT_TOLERANCE_PAUSED_SEC) {
            videoElement.currentTime = targetSec;
          }
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [videoElement, avInfo?.has_video, offsetSec]);

  return { avInfo, isLoading, videoError, videoElement, sessionId, videoAspect };
}
