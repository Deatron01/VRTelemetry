// src/frontend/VRTelemetry/src/services/ScienceMetrics.ts
//
// Four scientific-analysis domains computed from a loaded session's raw
// TelemetryFrame[] (already parsed into memory by TelemetryParser — see
// its parseFile/parseSessionId). Each function is a pure, self-contained
// transform: no network calls, no React, safe to call from useMemo().
//
// Every domain is deliberately documented with the assumption/simplification
// it makes, because these are *research-support* indices, not validated
// clinical instruments — the interpretation text this module returns says
// so explicitly rather than implying more precision than the underlying
// telemetry actually supports.

import type { TelemetryFrame, SessionMetadata } from '../types/telemetry';

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function downsample<T>(frames: T[], maxPoints: number): T[] {
  if (frames.length <= maxPoints) return frames;
  const step = Math.max(1, Math.floor(frames.length / maxPoints));
  return frames.filter((_, i) => i % step === 0);
}

function timeSec(f: TelemetryFrame, t0: number): number {
  return (f.timestamp_ns - t0) / 1e9;
}

function mean(values: number[]): number {
  if (!values.length) return 0;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

function linearRegressionSlope(xs: number[], ys: number[]): number {
  const n = xs.length;
  if (n < 2) return 0;
  const mx = mean(xs), my = mean(ys);
  let num = 0, den = 0;
  for (let i = 0; i < n; i++) {
    num += (xs[i] - mx) * (ys[i] - my);
    den += (xs[i] - mx) * (xs[i] - mx);
  }
  return den === 0 ? 0 : num / den;
}

/** Naive O(N*K) DFT power spectrum — fine for the few hundred points we ever feed it. */
function dftPower(signal: number[], sampleRateHz: number): { freqHz: number; power: number }[] {
  const N = signal.length;
  if (N < 4) return [];
  const meanVal = mean(signal);
  const detrended = signal.map(v => v - meanVal);
  const numBins = Math.floor(N / 2);
  const out: { freqHz: number; power: number }[] = [];
  for (let k = 1; k < numBins; k++) {
    let re = 0, im = 0;
    for (let n = 0; n < N; n++) {
      const angle = (2 * Math.PI * k * n) / N;
      re += detrended[n] * Math.cos(angle);
      im -= detrended[n] * Math.sin(angle);
    }
    out.push({ freqHz: (k * sampleRateHz) / N, power: re * re + im * im });
  }
  return out;
}

// ---------------------------------------------------------------------------
// 1. Cognitive Load / Mental Workload — Task-Evoked Pupillary Response (TEPR)
// ---------------------------------------------------------------------------
//
// Cognitive effort dilates the pupil above its resting size (the Task-Evoked
// Pupillary Response). The confound is the Pupillary Light Reflex (PLR):
// pupil size also tracks scene brightness, and this schema doesn't record a
// photometric/luminance channel (see TelemetryFrame — no ambient-light field
// exists yet), so a *true* PLR-compensated signal isn't derivable from
// today's telemetry. The best-effort proxy used here baselines each sample
// against the median pupil size recorded *within the same scene_id* rather
// than one global baseline — since brightness is roughly constant within a
// given virtual scene, subtracting the per-scene median cancels most of the
// scene-to-scene brightness confound while still surfacing within-scene,
// task-driven fluctuations. A dedicated ambient-luminance telemetry field
// would remove the need for this approximation entirely.

export interface CognitiveLoadPoint {
  time: number;
  pupilDiameter: number;
  tepr: number;
  cognitiveLoadIndex: number;
  sceneId: number;
}

export interface CognitiveLoadResult {
  timeSeries: CognitiveLoadPoint[];
  globalBaselinePupil: number;
  meanTepr: number;
  peakTepr: number;
  peakTime: number;
  interpretation: string;
}

export function computeCognitiveLoad(frames: TelemetryFrame[], nasaTlxMental?: number): CognitiveLoadResult {
  if (!frames.length) {
    return { timeSeries: [], globalBaselinePupil: 0, meanTepr: 0, peakTepr: 0, peakTime: 0, interpretation: 'No telemetry loaded.' };
  }
  const t0 = frames[0].timestamp_ns;
  const duration = timeSec(frames[frames.length - 1], t0);
  const baselineWindowSec = Math.min(10, Math.max(3, duration * 0.2));

  const pupilOf = (f: TelemetryFrame) => (f.left_pupil_size > 0 && f.right_pupil_size > 0) ? (f.left_pupil_size + f.right_pupil_size) / 2 : null;

  const baselineSamples = frames.filter(f => timeSec(f, t0) <= baselineWindowSec).map(pupilOf).filter((v): v is number => v !== null);
  const globalBaseline = baselineSamples.length ? mean(baselineSamples) : 0;

  // Per-scene baseline (PLR-proxy compensation) — median pupil size grouped by scene_id.
  const byScene = new Map<number, number[]>();
  for (const f of frames) {
    const p = pupilOf(f);
    if (p === null) continue;
    const arr = byScene.get(f.scene_id as unknown as number) ?? [];
    arr.push(p);
    byScene.set(f.scene_id as unknown as number, arr);
  }
  const sceneBaseline = new Map<number, number>();
  byScene.forEach((vals, sceneId) => {
    if (vals.length >= 10) {
      const sorted = [...vals].sort((a, b) => a - b);
      sceneBaseline.set(sceneId, sorted[Math.floor(sorted.length / 2)]);
    } else {
      sceneBaseline.set(sceneId, globalBaseline || mean(vals));
    }
  });

  const sampled = downsample(frames, 300);
  const timeSeries: CognitiveLoadPoint[] = [];
  for (const f of sampled) {
    const p = pupilOf(f);
    if (p === null) continue;
    const sceneId = f.scene_id as unknown as number;
    const base = sceneBaseline.get(sceneId) || globalBaseline || p;
    const tepr = base > 0 ? ((p - base) / base) * 100 : 0;
    timeSeries.push({
      time: timeSec(f, t0),
      pupilDiameter: p,
      tepr,
      cognitiveLoadIndex: Math.max(0, Math.min(100, tepr * 4)), // rescaled for a readable 0-100 display band
      sceneId,
    });
  }

  const teprValues = timeSeries.map(p => p.tepr);
  const meanTepr = mean(teprValues);
  let peakTepr = 0, peakTime = 0;
  for (const p of timeSeries) {
    if (p.tepr > peakTepr) { peakTepr = p.tepr; peakTime = p.time; }
  }

  let interpretation = globalBaseline === 0
    ? 'No valid pupillometry signal in this session — cognitive load cannot be estimated (check eye-tracking hardware/driver).'
    : `Mean pupil dilation ran ${meanTepr.toFixed(1)}% above each scene's own resting baseline, peaking at +${peakTepr.toFixed(1)}% around ${peakTime.toFixed(1)}s. `
      + (meanTepr > 15 ? 'This is a notably elevated dilation pattern, consistent with sustained cognitive effort. '
        : meanTepr > 5 ? 'This is a mild-to-moderate dilation pattern. ' : 'Dilation stayed close to baseline for most of the session. ');
  if (typeof nasaTlxMental === 'number') {
    interpretation += `Self-reported NASA-TLX Mental Demand for this session was ${nasaTlxMental.toFixed(0)}/100 — `
      + ((meanTepr > 10) === (nasaTlxMental > 50)
        ? 'directionally consistent with the pupillometry-derived load estimate above.'
        : 'notably different from the pupillometry-derived load estimate, which is itself worth investigating.');
  }

  return { timeSeries, globalBaselinePupil: globalBaseline, meanTepr, peakTepr, peakTime, interpretation };
}

// ---------------------------------------------------------------------------
// 2. Vestibular Function & Postural Stability / Cybersickness Risk
// ---------------------------------------------------------------------------
//
// Head (HMD) trajectory sway is the standard posturography substrate for
// this kind of analysis. hmd_pos_x/hmd_pos_z are treated as the horizontal
// plane (Y assumed up, matching this engine's coordinate convention
// elsewhere). The literature (e.g. Munafo et al., 2017) reports that
// low-frequency postural sway increases *before* a subject consciously
// reports simulator sickness — this is the rationale for the low-frequency
// spectral energy ratio and the rising sway-velocity trend below being
// framed as an early-warning indicator, not a diagnosis.

export interface PosturalStabilityResult {
  swayTrend: { time: number; swayVelocity: number }[];
  totalPathLengthM: number;
  meanSwayVelocity: number;
  swayEllipseAreaM2: number;
  lowFrequencyEnergyRatio: number;
  riskTrend: { windowIndex: number; time: number; risk: number }[];
  riskTrendSlope: number;
  interpretation: string;
}

export function computePosturalStability(frames: TelemetryFrame[], ssqTotalSeverity?: number): PosturalStabilityResult {
  const valid = frames.filter(f => f.hmd_tracking_valid > 0);
  if (valid.length < 3) {
    return {
      swayTrend: [], totalPathLengthM: 0, meanSwayVelocity: 0, swayEllipseAreaM2: 0,
      lowFrequencyEnergyRatio: 0, riskTrend: [], riskTrendSlope: 0,
      interpretation: 'Insufficient valid HMD tracking to assess postural stability.',
    };
  }
  const t0 = valid[0].timestamp_ns;

  let totalPathLengthM = 0;
  const sway: { time: number; speed: number }[] = [];
  for (let i = 1; i < valid.length; i++) {
    const prev = valid[i - 1], cur = valid[i];
    const dt = (cur.timestamp_ns - prev.timestamp_ns) / 1e9;
    if (dt <= 0) continue;
    const dx = cur.hmd_pos_x - prev.hmd_pos_x;
    const dz = cur.hmd_pos_z - prev.hmd_pos_z;
    const planarDist = Math.sqrt(dx * dx + dz * dz);
    if (planarDist > 0.5) continue; // reject teleport/re-center outliers
    totalPathLengthM += planarDist;
    sway.push({ time: timeSec(cur, t0), speed: planarDist / dt });
  }

  // 95% confidence sway ellipse area (Prieto et al., 1996) over horizontal head position.
  const xs = valid.map(f => f.hmd_pos_x), zs = valid.map(f => f.hmd_pos_z);
  const mx = mean(xs), mz = mean(zs);
  let varX = 0, varZ = 0, covXZ = 0;
  for (let i = 0; i < valid.length; i++) {
    varX += (xs[i] - mx) ** 2;
    varZ += (zs[i] - mz) ** 2;
    covXZ += (xs[i] - mx) * (zs[i] - mz);
  }
  const n = valid.length;
  varX /= n; varZ /= n; covXZ /= n;
  const det = varX * varZ - covXZ * covXZ;
  const CHI_SQUARE_95_2DOF = 5.991;
  const swayEllipseAreaM2 = det > 0 ? Math.PI * CHI_SQUARE_95_2DOF * Math.sqrt(det) : 0;

  // Windowed sway-velocity trend (10 windows across the session) -> risk trend + slope.
  const swayDownsampled = downsample(sway, 300);
  const duration = swayDownsampled.length ? swayDownsampled[swayDownsampled.length - 1].time : 0;
  const numWindows = Math.min(10, Math.max(2, Math.floor(duration / 5)));
  const windowSec = duration / numWindows || 1;
  const riskTrend: { windowIndex: number; time: number; risk: number }[] = [];
  const windowSpeeds: number[] = [];
  for (let w = 0; w < numWindows; w++) {
    const inWindow = sway.filter(s => s.time >= w * windowSec && s.time < (w + 1) * windowSec).map(s => s.speed);
    const avgSpeed = mean(inWindow);
    windowSpeeds.push(avgSpeed);
    riskTrend.push({ windowIndex: w, time: (w + 0.5) * windowSec, risk: 0 }); // risk normalized below
  }
  const maxWindowSpeed = Math.max(...windowSpeeds, 1e-6);
  riskTrend.forEach((r, i) => { r.risk = Math.round((windowSpeeds[i] / maxWindowSpeed) * 100); });
  const riskTrendSlope = linearRegressionSlope(riskTrend.map(r => r.windowIndex), windowSpeeds);

  // Low-frequency spectral energy ratio of the whole-session sway-speed signal.
  const speedSeries = swayDownsampled.map(s => s.speed);
  const effectiveSampleRate = speedSeries.length && duration > 0 ? speedSeries.length / duration : 1;
  const spectrum = dftPower(speedSeries, effectiveSampleRate);
  const totalPower = spectrum.reduce((a, b) => a + b.power, 0) || 1;
  const lowFreqPower = spectrum.filter(b => b.freqHz < 0.5).reduce((a, b) => a + b.power, 0);
  const lowFrequencyEnergyRatio = lowFreqPower / totalPower;

  const meanSwayVelocity = mean(sway.map(s => s.speed));
  const risingTrend = riskTrendSlope > 0.01;

  let interpretation = `Total head-sway path length was ${totalPathLengthM.toFixed(2)}m over the session `
    + `(mean sway velocity ${meanSwayVelocity.toFixed(3)} m/s, 95% sway ellipse area ${swayEllipseAreaM2.toFixed(4)} m²). `
    + `Low-frequency (<0.5Hz) sway accounted for ${(lowFrequencyEnergyRatio * 100).toFixed(0)}% of spectral energy — `
    + (lowFrequencyEnergyRatio > 0.6 ? 'a low-frequency-dominant sway pattern, the profile the literature associates with rising visually-induced motion sickness risk. '
      : 'not a low-frequency-dominant pattern. ')
    + (risingTrend ? 'Sway velocity trended upward across the session, consistent with worsening postural instability over time — worth flagging as an early-warning signal even if the subject did not report symptoms. '
      : 'Sway velocity did not show a clear rising trend across the session. ');
  if (typeof ssqTotalSeverity === 'number') {
    interpretation += `Reported SSQ Total Severity for this session: ${ssqTotalSeverity.toFixed(1)}.`;
  }

  return {
    swayTrend: downsample(sway.map(s => ({ time: s.time, swayVelocity: s.speed })), 300),
    totalPathLengthM, meanSwayVelocity, swayEllipseAreaM2, lowFrequencyEnergyRatio,
    riskTrend, riskTrendSlope, interpretation,
  };
}

// ---------------------------------------------------------------------------
// 3. Motor Function & Kinematics — smoothness, reach, bilateral symmetry
// ---------------------------------------------------------------------------
//
// Reach is computed as Euclidean controller-to-HMD distance (a head-centered
// proxy for body-centered reach — a full body-relative frame would need the
// HMD's yaw to un-rotate the controller offset, which this telemetry schema
// doesn't need for a *distance* metric since rotation doesn't change vector
// length). Normalized jerk follows Hogan & Sternad (2009), a standard
// dimensionless movement-smoothness index used in motor-control and stroke
// rehabilitation research — lower is smoother/healthier.

export interface HandKinematics {
  meanSpeed: number;
  maxReachM: number;
  reachPctOfArmLength: number | null;
  normalizedJerk: number;
  timeSeries: { time: number; speed: number; reach: number }[];
}

export interface MotorKinematicsResult {
  left: HandKinematics;
  right: HandKinematics;
  speedSymmetryIndex: number;
  reachSymmetryIndex: number;
  interpretation: string;
}

function computeHandKinematics(
  frames: TelemetryFrame[], side: 'left' | 'right', armLengthM: number | undefined, t0: number,
): HandKinematics {
  const validFrames = frames.filter(f => (f as any)[`${side}_tracking_valid`] === undefined || (f as any)[`${side}_tracking_valid`] > 0);

  const speeds: number[] = [];
  const jerks: number[] = [];
  const timeSeries: { time: number; speed: number; reach: number }[] = [];
  let maxReach = 0;
  let prevSpeed: number | null = null;
  let prevAccel: number | null = null;
  let pathLength = 0;

  for (let i = 1; i < validFrames.length; i++) {
    const prev = validFrames[i - 1], cur = validFrames[i];
    const px = (cur as any)[`${side}_pos_x`], py = (cur as any)[`${side}_pos_y`], pz = (cur as any)[`${side}_pos_z`];
    const ppx = (prev as any)[`${side}_pos_x`], ppy = (prev as any)[`${side}_pos_y`], ppz = (prev as any)[`${side}_pos_z`];
    if ([px, py, pz, ppx, ppy, ppz].some(v => v === undefined || v === null)) continue;

    const dt = (cur.timestamp_ns - prev.timestamp_ns) / 1e9;
    if (dt <= 0) continue;
    const dx = px - ppx, dy = py - ppy, dz = pz - ppz;
    const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
    if (dist > 3) continue; // reject teleport/init-frame outliers
    const speed = dist / dt;
    pathLength += dist;

    const reach = Math.sqrt(
      (px - cur.hmd_pos_x) ** 2 + (py - cur.hmd_pos_y) ** 2 + (pz - cur.hmd_pos_z) ** 2,
    );
    if (reach > maxReach && reach < 2) maxReach = reach; // 2m sanity bound

    if (prevSpeed !== null) {
      const accel = (speed - prevSpeed) / dt;
      if (prevAccel !== null) {
        const jerk = (accel - prevAccel) / dt;
        jerks.push(jerk);
      }
      prevAccel = accel;
    }
    prevSpeed = speed;
    speeds.push(speed);
    timeSeries.push({ time: timeSec(cur, t0), speed, reach });
  }

  const T = timeSeries.length ? timeSeries[timeSeries.length - 1].time - timeSeries[0].time : 0;
  const jerkIntegral = jerks.reduce((acc, j) => acc + j * j, 0) * (T / Math.max(1, jerks.length));
  const normalizedJerk = (T > 0 && pathLength > 0)
    ? Math.sqrt(0.5 * jerkIntegral * Math.pow(T, 5) / (pathLength * pathLength))
    : 0;

  return {
    meanSpeed: mean(speeds),
    maxReachM: maxReach,
    reachPctOfArmLength: armLengthM ? (maxReach / armLengthM) * 100 : null,
    normalizedJerk,
    timeSeries: downsample(timeSeries, 300),
  };
}

export function computeMotorKinematics(frames: TelemetryFrame[], metadata: SessionMetadata | null): MotorKinematicsResult {
  if (!frames.length) {
    const empty: HandKinematics = { meanSpeed: 0, maxReachM: 0, reachPctOfArmLength: null, normalizedJerk: 0, timeSeries: [] };
    return { left: empty, right: empty, speedSymmetryIndex: 0, reachSymmetryIndex: 0, interpretation: 'No telemetry loaded.' };
  }
  const t0 = frames[0].timestamp_ns;
  const left = computeHandKinematics(frames, 'left', metadata?.arm_length_left, t0);
  const right = computeHandKinematics(frames, 'right', metadata?.arm_length_right, t0);

  const symmetry = (a: number, b: number) => (a + b) > 0 ? Math.abs(a - b) / (a + b) : 0;
  const speedSymmetryIndex = symmetry(left.meanSpeed, right.meanSpeed);
  const reachSymmetryIndex = symmetry(left.maxReachM, right.maxReachM);

  let interpretation = '';
  if (left.timeSeries.length === 0 && right.timeSeries.length === 0) {
    interpretation = 'Controller tracking data is completely absent or invalid for this session. Motor kinematics and bimanual symmetry cannot be assessed without hand tracking.';
  } else {
    interpretation = `Left-hand normalized jerk ${left.timeSeries.length ? left.normalizedJerk.toFixed(1) : 'N/A'}, right-hand ${right.timeSeries.length ? right.normalizedJerk.toFixed(1) : 'N/A'} `
      + '(lower = smoother movement; the two are only comparable within this same session/task). '
      + `Bilateral speed symmetry index: ${(speedSymmetryIndex * 100).toFixed(1)}% asymmetry `
      + (speedSymmetryIndex > 0.25 ? '— a pronounced side-to-side difference, the kind of asymmetry monitored in upper-limb rehabilitation (e.g. post-stroke). '
        : '— reasonably balanced bilateral use. ');
    if (left.reachPctOfArmLength !== null || right.reachPctOfArmLength !== null) {
      interpretation += `Peak reach reached ${(left.reachPctOfArmLength ?? 0).toFixed(0)}% (L) / ${(right.reachPctOfArmLength ?? 0).toFixed(0)}% (R) `
        + 'of this subject\'s calibrated arm length.';
    } else {
      interpretation += 'Arm length calibration is not recorded for this session, so reach could only be reported in absolute meters, not normalized to the subject\'s body size.';
    }
  }

  return { left, right, speedSymmetryIndex, reachSymmetryIndex, interpretation };
}

// ---------------------------------------------------------------------------
// 4. Anthropometric Normalization & Physical Exertion
// ---------------------------------------------------------------------------

export interface ExertionResult {
  restingHrEstimate: number;
  peakHr: number;
  hrDriftBpm: number;
  hrDriftRatePerMin: number;
  exertionIndex: number;
  timeSeries: { time: number; hr: number | null; kinematicIntensity: number }[];
  interpretation: string;
}

export function computeExertionProfile(
  frames: TelemetryFrame[], nasaTlxPhysical?: number, thermalComfort?: string,
): ExertionResult {
  if (!frames.length) {
    return { restingHrEstimate: 0, peakHr: 0, hrDriftBpm: 0, hrDriftRatePerMin: 0, exertionIndex: 0, timeSeries: [], interpretation: 'No telemetry loaded.' };
  }
  const t0 = frames[0].timestamp_ns;
  const duration = timeSec(frames[frames.length - 1], t0);
  const hrFrames = frames.filter(f => f.heart_rate_bpm > 0);

  const baselineWindowSec = Math.min(10, Math.max(3, duration * 0.2));
  const restingSamples = hrFrames.filter(f => timeSec(f, t0) <= baselineWindowSec).map(f => f.heart_rate_bpm);
  const restingHrEstimate = restingSamples.length ? mean(restingSamples) : mean(hrFrames.map(f => f.heart_rate_bpm));
  const peakHr = hrFrames.length ? Math.max(...hrFrames.map(f => f.heart_rate_bpm)) : 0;

  const mid = duration / 2;
  const firstHalf = hrFrames.filter(f => timeSec(f, t0) < mid).map(f => f.heart_rate_bpm);
  const secondHalf = hrFrames.filter(f => timeSec(f, t0) >= mid).map(f => f.heart_rate_bpm);
  const hrDriftBpm = (secondHalf.length && firstHalf.length) ? mean(secondHalf) - mean(firstHalf) : 0;
  const halfDurationMin = (duration / 60) / 2;
  const hrDriftRatePerMin = halfDurationMin > 0 ? hrDriftBpm / halfDurationMin : 0;

  const sampled = downsample(frames, 300);
  const timeSeries = sampled.map((f, i, arr) => {
    let kinematicIntensity = 0;
    if (i > 0) {
      const prev = arr[i - 1];
      const dt = (f.timestamp_ns - prev.timestamp_ns) / 1e9;
      if (dt > 0) {
        const dx = f.hmd_pos_x - prev.hmd_pos_x, dy = f.hmd_pos_y - prev.hmd_pos_y, dz = f.hmd_pos_z - prev.hmd_pos_z;
        const headSpeed = Math.sqrt(dx * dx + dy * dy + dz * dz) / dt;
        kinematicIntensity = Math.min(headSpeed, 3);
      }
    }
    return { time: timeSec(f, t0), hr: f.heart_rate_bpm > 0 ? f.heart_rate_bpm : null, kinematicIntensity };
  });

  const hrElevationFactor = restingHrEstimate > 0 ? Math.max(0, (peakHr - restingHrEstimate) / restingHrEstimate) : 0;
  const kinematicFactor = Math.min(1, mean(timeSeries.map(p => p.kinematicIntensity)) / 1.5);
  const exertionIndex = Math.max(0, Math.min(100, (hrElevationFactor * 60 + kinematicFactor * 40)));

  let interpretation = restingHrEstimate > 0
    ? `Estimated resting HR ${restingHrEstimate.toFixed(0)} BPM, peak ${peakHr.toFixed(0)} BPM, `
      + `drift of ${hrDriftBpm >= 0 ? '+' : ''}${hrDriftBpm.toFixed(1)} BPM between session halves `
      + `(${hrDriftRatePerMin >= 0 ? '+' : ''}${hrDriftRatePerMin.toFixed(2)} BPM/min) — classic cardiovascular drift analysis assumes `
      + 'constant workload throughout, which a free-form VR session may not satisfy, so treat the rate as indicative rather than clinical. '
    : 'No heart-rate telemetry available for this session — exertion could only be estimated from motion intensity. ';
  interpretation += `Composite exertion index: ${exertionIndex.toFixed(0)}/100 (blends HR elevation and movement intensity). `;
  if (typeof nasaTlxPhysical === 'number') {
    interpretation += `Self-reported NASA-TLX Physical Demand: ${nasaTlxPhysical.toFixed(0)}/100.`;
  }
  if (thermalComfort) {
    interpretation += ` Reported thermal comfort: ${thermalComfort.replace(/_/g, ' ')}.`;
  }

  return { restingHrEstimate, peakHr, hrDriftBpm, hrDriftRatePerMin, exertionIndex, timeSeries, interpretation };
}
