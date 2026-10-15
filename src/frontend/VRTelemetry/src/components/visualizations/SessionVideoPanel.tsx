import { useEffect, useMemo, useRef, useState } from 'react';
import { Video, Loader2 } from 'lucide-react';
import { useTelemetryStore } from '../../store/useTelemetryStore';
import { InfoTooltip } from '../InfoTooltip';

/** Subset of GET /api/sessions/{id}/av-recording this panel actually reads.
    Mirrors SessionExplorer.tsx's own AvRecordingInfo rather than importing
    it — this project has no shared API-response types yet (VRT-18 backlog). */
interface AvRecordingInfo {
  started_at_utc: string | null;
  has_video: boolean;
  video_deleted_at_utc: string | null;
  failure_reason: string | null;
}

/** Backend timestamp columns (src/utils/clock.py::as_stored) are written as
    naive-UTC ISO strings -- no trailing "Z"/offset, e.g.
    "2026-09-14T10:23:11.123456". JS's `Date` reads a zone-less string as
    *local* time, which is the exact bug clock.py's own module docstring
    documents for the hub dashboard (VRT-21): a value would silently shift by
    the viewer's UTC offset. Every value read here is explicitly anchored to
    UTC before parsing, the same way clock.py's `parse_utc` does server-side. */
function parseNaiveUtcMs(value: string | null | undefined): number | null {
  if (!value) return null;
  const iso = value.includes(' ') ? value.replace(' ', 'T') : value;
  const withZone = /[zZ]|[+-]\d{2}:\d{2}$/.test(iso) ? iso : `${iso}Z`;
  const ms = Date.parse(withZone);
  return Number.isNaN(ms) ? null : ms;
}

/** How far off the video is allowed to drift from the telemetry clock before
    we hard-seek it back into place. Two thresholds: a looser one while
    playing (native playback already keeps pace; frequent seeking during
    playback causes visible stutter) and a tight one while paused (a scrub on
    the transport bar should move the video immediately, even by a frame). */
const DRIFT_TOLERANCE_PLAYING_SEC = 0.35;
const DRIFT_TOLERANCE_PAUSED_SEC = 0.05;

const EmptyNote = ({ text }: { text: string }) => (
  <p className="m-0 max-w-[240px] px-4 text-center text-[11px] leading-relaxed text-white/40">{text}</p>
);

/**
 * Plays a session's recorded screen capture (src/av_recording/*) alongside
 * the reconstructed 3D gaze replay in SpatialViewer, driven by the same
 * global playback state (useTelemetryStore) that drives everything else on
 * the Spatial Analysis tab -- so "what the software looked like on screen"
 * and "where the participant was looking" scrub together.
 *
 * There is no independent scrubber or play button here on purpose: the
 * AppShell footer transport bar is the single source of truth for playback
 * position across every panel on this tab, matching how SpatialViewer's own
 * VRRig/LivePoRCursor have no controls of their own either.
 *
 * Sync is best-effort, not frame-exact: the telemetry clock and the video's
 * own internal clock are two independent recordings that start a moment
 * apart (the A/V capture is only started *after* the telemetry engine is
 * already running -- see src/interfaces/api/routers/recording.py's
 * `_maybe_start_av_recording` and its comment on why). The offset between
 * them is estimated from each recording's logged wall-clock start time,
 * which is itself only accurate to about a second.
 */
export const SessionVideoPanel = () => {
  const metadata = useTelemetryStore((state) => state.metadata);
  const sessionId = metadata?.session_id;

  const [avInfo, setAvInfo] = useState<AvRecordingInfo | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [loadProgress, setLoadProgress] = useState(0);
  const [videoLoading, setVideoLoading] = useState(true);
  const [videoError, setVideoError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    setAvInfo(null);
    setVideoError(null);
    if (!sessionId) {
      setIsLoading(false);
      setLoadProgress(0);
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    setLoadProgress(0);
    fetch(`http://localhost:8000/api/sessions/${sessionId}/av-recording`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled) {
          setAvInfo(data);
          setLoadProgress(100);
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
    };
  }, [sessionId]);

  const offsetSec = useMemo(() => {
    const sessionStartMs = parseNaiveUtcMs(metadata?.start_timestamp_utc);
    const videoStartMs = parseNaiveUtcMs(avInfo?.started_at_utc);
    if (sessionStartMs === null || videoStartMs === null) return 0;
    return (videoStartMs - sessionStartMs) / 1000;
  }, [metadata?.start_timestamp_utc, avInfo?.started_at_utc]);

  useEffect(() => {
    if (!avInfo?.has_video) return;
    const video = videoRef.current;
    if (!video) return;

    let raf = 0;
    const tick = () => {
      const state = useTelemetryStore.getState();
      const { frames, currentFrameIdx, isPlaying, playbackSpeed } = state;
      const frame = frames[currentFrameIdx];

      // readyState >= 1 (HAVE_METADATA) is when currentTime/duration are safe
      // to read and set -- before that, seeking is a silent no-op at best.
      // `frame` is guarded the same way VRRig/LivePoRCursor guard it in
      // SpatialViewer.tsx -- a loadSession() transition can be observed
      // mid-update from outside React's render cycle via getState().
      if (frame && frames.length > 1 && video.readyState >= 1) {
        const elapsedSec = (frame.timestamp_ns - frames[0].timestamp_ns) / 1e9;
        const rawTargetSec = elapsedSec - offsetSec;
        const targetSec = Number.isFinite(video.duration)
          ? Math.min(Math.max(rawTargetSec, 0), video.duration)
          : Math.max(rawTargetSec, 0);

        if (isPlaying) {
          if (video.paused) video.play().catch(() => {});
          if (Math.abs(video.playbackRate - playbackSpeed) > 0.001) {
            video.playbackRate = playbackSpeed;
          }
          if (Math.abs(video.currentTime - targetSec) > DRIFT_TOLERANCE_PLAYING_SEC) {
            video.currentTime = targetSec;
          }
        } else {
          if (!video.paused) video.pause();
          if (Math.abs(video.currentTime - targetSec) > DRIFT_TOLERANCE_PAUSED_SEC) {
            video.currentTime = targetSec;
          }
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [avInfo?.has_video, offsetSec]);

  return (
    <div className="relative flex h-full w-full flex-col overflow-hidden rounded-xl border border-research-border bg-slate-900 shadow-inner">
      <div className="flex flex-none items-center gap-1.5 px-3 pb-2 pt-3">
        <Video className="h-3.5 w-3.5 text-blue-400" />
        <span className="text-[10px] font-bold uppercase tracking-widest text-white/70">Recorded View</span>
        <InfoTooltip id="spatial.recorded-view" side="right" className="info-trigger-dark" />
      </div>

      <div className="relative mx-3 mb-3 flex min-h-0 flex-1 items-center justify-center overflow-hidden rounded-lg bg-black">
        {!sessionId ? (
          <EmptyNote text="Only available for sessions opened from Session Explorer, not a dropped .parquet file." />
        ) : isLoading ? (
          <div className="flex items-center justify-center h-full">
            <Loader2 className="animate-spin text-white" />
            <span className="ml-2 text-white">Loading video…</span>
          </div>
        ) : videoError ? (
          <EmptyNote text={videoError} />
        ) : !avInfo ? (
          <EmptyNote text="No screen recording for this session." />
        ) : avInfo.has_video ? (
          <div className="relative w-full h-full">
            {/* Metadata load progress bar */}
            {isLoading && (
              <div className="absolute top-0 left-0 w-full">
                <div className="h-1 bg-gray-600">
                  <div
                    className="h-1 bg-blue-500 transition-all duration-300"
                    style={{ width: `${loadProgress}%` }}
                  />
                </div>
              </div>
            )}
            {/* Video loading overlay */}
            {videoLoading && (
              <div className="absolute inset-0 flex items-center justify-center bg-black bg-opacity-50">
                <Loader2 className="animate-spin text-white" />
                <span className="ml-2 text-white">Loading video...</span>
              </div>
            )}
            <video
              ref={videoRef}
              src={`http://localhost:8000/api/sessions/${sessionId}/av-recording/video`}
              className="h-full w-full object-contain"
              playsInline
              onError={() => setVideoError('Could not load the recorded video.')}
              onCanPlay={() => setVideoLoading(false)}
            />
          </div>
        ) : avInfo.video_deleted_at_utc ? (
          <EmptyNote
            text={`Raw video deleted under the configured retention period (GDPR Art. 5(1)(e)) on ${avInfo.video_deleted_at_utc}.`}
          />
        ) : (
          <EmptyNote text={avInfo.failure_reason || 'No video was captured for this session.'} />
        )}
      </div>

      {avInfo?.has_video && (
        <p className="m-0 flex-none px-3 pb-2.5 text-[10px] text-white/40">
          Synced to the transport bar below — approximate (±1–2s), from each recording's logged start time.
        </p>
      )}
    </div>
  );
};
