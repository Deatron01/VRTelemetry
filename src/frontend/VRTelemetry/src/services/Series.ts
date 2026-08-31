// src/frontend/VRTelemetry/src/services/Series.ts
//
// Small, pure helpers for turning a session's frame array into the bucketed
// series the Vitrum design's inline sparklines and meters draw. Kept separate
// from TelemetryParser (which computes the session-level summary once at load)
// because these are cheap, view-local reductions that several pages need at
// different bucket counts.
//
// Everything here is defensive about missing/NaN channels: telemetry rows can
// legitimately lack controller or heart-rate columns, and a chart that renders
// an empty well is better than one that throws.

import type { TelemetryFrame } from '../types/telemetry';

const NS_PER_S = 1e9;

function finite(n: number | undefined | null): number | null {
  return typeof n === 'number' && Number.isFinite(n) ? n : null;
}

/** Split [0, length) into `buckets` contiguous index ranges. */
function ranges(length: number, buckets: number): [number, number][] {
  if (length <= 0 || buckets <= 0) return [];
  const n = Math.min(buckets, length);
  const out: [number, number][] = [];
  for (let b = 0; b < n; b++) {
    const start = Math.floor((b * length) / n);
    const end = Math.floor(((b + 1) * length) / n);
    if (end > start) out.push([start, end]);
  }
  return out;
}

/**
 * Mean of `pick` over each bucket. Buckets whose samples are all missing come
 * back as null so the caller can decide between "gap" and "zero" — they are
 * very different claims about a sensor.
 */
export function bucketMean(
  frames: TelemetryFrame[],
  pick: (f: TelemetryFrame, i: number) => number | null | undefined,
  buckets = 48,
): (number | null)[] {
  return ranges(frames.length, buckets).map(([start, end]) => {
    let sum = 0;
    let count = 0;
    for (let i = start; i < end; i++) {
      const v = finite(pick(frames[i], i) as number);
      if (v !== null) { sum += v; count++; }
    }
    return count > 0 ? sum / count : null;
  });
}

/** Effective sampling rate (Hz) within each bucket, from frame timestamps. */
export function bucketRateHz(frames: TelemetryFrame[], buckets = 48): (number | null)[] {
  return ranges(frames.length, buckets).map(([start, end]) => {
    if (end - start < 2) return null;
    const dt = (frames[end - 1].timestamp_ns - frames[start].timestamp_ns) / NS_PER_S;
    return dt > 0 ? (end - 1 - start) / dt : null;
  });
}

/**
 * Frames missing from each bucket, inferred from gaps in `frame_index`.
 * A recorder that never drops emits a strictly +1 sequence, so anything larger
 * is a real hole rather than an artifact of downsampling on load — which is why
 * this reads frame_index and not timestamps.
 */
export function bucketDrops(frames: TelemetryFrame[], buckets = 48): number[] {
  return ranges(frames.length, buckets).map(([start, end]) => {
    let drops = 0;
    for (let i = Math.max(start, 1); i < end; i++) {
      const gap = frames[i].frame_index - frames[i - 1].frame_index - 1;
      if (gap > 0) drops += gap;
    }
    return drops;
  });
}

export interface IntervalStats {
  meanHz: number;
  sigmaHz: number;
  jitterMs: number;
  maxIntervalMs: number;
}

/**
 * Inter-frame interval statistics. `jitterMs` is the mean absolute deviation
 * from the mean interval (not the standard deviation) — the figure a timing
 * engineer expects to see next to a nominal rate.
 */
export function intervalStats(frames: TelemetryFrame[]): IntervalStats | null {
  if (frames.length < 3) return null;
  const intervals: number[] = [];
  for (let i = 1; i < frames.length; i++) {
    const dt = (frames[i].timestamp_ns - frames[i - 1].timestamp_ns) / 1e6; // ms
    if (Number.isFinite(dt) && dt > 0) intervals.push(dt);
  }
  if (intervals.length === 0) return null;

  const mean = intervals.reduce((a, b) => a + b, 0) / intervals.length;
  const variance = intervals.reduce((a, b) => a + (b - mean) ** 2, 0) / intervals.length;
  const jitter = intervals.reduce((a, b) => a + Math.abs(b - mean), 0) / intervals.length;
  const maxInterval = intervals.reduce((a, b) => (b > a ? b : a), 0);

  // σ in Hz, propagated from σ in ms: |d(1000/t)/dt| = 1000/t².
  const sigmaHz = mean > 0 ? (Math.sqrt(variance) * 1000) / (mean * mean) : 0;

  return {
    meanHz: mean > 0 ? 1000 / mean : 0,
    sigmaHz,
    jitterMs: jitter,
    maxIntervalMs: maxInterval,
  };
}

/** Euclidean speed (units/s) of a positional channel, per bucket. */
export function bucketSpeed(
  frames: TelemetryFrame[],
  keys: { x: keyof TelemetryFrame; y: keyof TelemetryFrame; z: keyof TelemetryFrame },
  buckets = 48,
): (number | null)[] {
  return bucketMean(frames, (f, i) => {
    if (i === 0) return null;
    const prev = frames[i - 1];
    const dx = finite(f[keys.x] as number);
    const dy = finite(f[keys.y] as number);
    const dz = finite(f[keys.z] as number);
    const px = finite(prev[keys.x] as number);
    const py = finite(prev[keys.y] as number);
    const pz = finite(prev[keys.z] as number);
    if (dx === null || dy === null || dz === null || px === null || py === null || pz === null) return null;
    const dt = (f.timestamp_ns - prev.timestamp_ns) / NS_PER_S;
    if (!(dt > 0)) return null;
    return Math.hypot(dx - px, dy - py, dz - pz) / dt;
  }, buckets);
}

/** Fraction (0–1) of frames in each bucket where `flag` is truthy. */
export function bucketValidity(
  frames: TelemetryFrame[],
  flag: (f: TelemetryFrame) => number | undefined,
  buckets = 48,
): (number | null)[] {
  return bucketMean(frames, (f) => {
    const v = flag(f);
    return v === undefined ? null : v ? 1 : 0;
  }, buckets);
}

/** Overall fraction (0–100 %) of frames where `flag` is truthy, or null if absent. */
export function validityPct(frames: TelemetryFrame[], flag: (f: TelemetryFrame) => number | undefined): number | null {
  let seen = 0;
  let ok = 0;
  for (const f of frames) {
    const v = flag(f);
    if (v === undefined) continue;
    seen++;
    if (v) ok++;
  }
  return seen > 0 ? (ok / seen) * 100 : null;
}

/**
 * Map a series to SVG polyline points inside `width` × `height`.
 * Null buckets are skipped rather than plotted at zero, and a flat series is
 * centred instead of collapsing onto the baseline.
 */
export function toPolyline(
  values: (number | null)[],
  width: number,
  height: number,
  opts: { pad?: number; min?: number; max?: number } = {},
): string {
  const pad = opts.pad ?? 2;
  const present = values.filter((v): v is number => v !== null);
  if (present.length < 2) return '';

  const lo = opts.min ?? Math.min(...present);
  const hi = opts.max ?? Math.max(...present);
  const span = hi - lo;
  const usable = height - pad * 2;
  const step = values.length > 1 ? width / (values.length - 1) : width;

  const pts: string[] = [];
  values.forEach((v, i) => {
    if (v === null) return;
    const norm = span > 0 ? (v - lo) / span : 0.5;
    const y = pad + (1 - norm) * usable;
    pts.push(`${(i * step).toFixed(1)},${y.toFixed(1)}`);
  });
  return pts.join(' ');
}

/** Bar geometry for a column chart drawn in `width` × `height`. */
export function toBars(
  values: number[],
  width: number,
  height: number,
  opts: { barWidth?: number; baseline?: number } = {},
): { x: number; y: number; width: number; height: number }[] {
  const max = Math.max(...values, 0);
  if (!(max > 0)) return [];
  const barWidth = opts.barWidth ?? 4;
  const baseline = opts.baseline ?? height - 2;
  const step = values.length > 0 ? width / values.length : width;

  return values.flatMap((v, i) => {
    if (!(v > 0)) return [];
    const h = Math.max(2, (v / max) * (baseline - 2));
    return [{ x: i * step, y: baseline - h, width: barWidth, height: h }];
  });
}
