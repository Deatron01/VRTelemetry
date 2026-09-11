// src/frontend/VRTelemetry/src/content/infoDefinitions.ts
//
// Centralized copy for the app's contextual-help system (InfoTooltip). Every
// entry here is written from what the code actually does — see the file/line
// referenced in each comment block — not from assumed textbook definitions.
// Where a figure's exact meaning couldn't be pinned down from the source
// (e.g. pupil-size units, which vary per eye-tracking driver), the entry says
// so explicitly instead of guessing.
//
// Add new copy here rather than inline in a component: this keeps every
// definition in one place, in plain language a researcher without a software
// background can act on, and it's what InfoTooltip's `id` prop looks up.

/** Where a displayed figure actually comes from — shown as a small tag on the panel. */
export type Provenance =
  | 'raw'          // written straight from the recorder/runtime, unprocessed
  | 'device'       // reported by the headset/sensor hardware or its driver
  | 'measured'     // a direct sensor reading, or a simple aggregate of one (mean/peak)
  | 'derived'      // computed from raw telemetry by this app (formula, index, geometry)
  | 'estimated'    // inferred/approximated where a direct measurement isn't available
  | 'reported'     // self-reported by the participant (questionnaire)
  | 'aggregated';  // a summary rolled up from many underlying samples

export interface InfoContent {
  title: string;
  description: string;
  unit?: string;
  provenance?: Provenance;
  source?: string;
  limitations?: string;
}

export const INFO_REGISTRY: Record<string, InfoContent> = {

  // ---------------------------------------------------------------------
  // Navigation (components/layout/AppShell.tsx — NAV_GROUPS)
  // ---------------------------------------------------------------------

  'nav.record': {
    title: 'Live Acquisition',
    description: 'Configure the VR tracking backend and central-server sync target, then start or stop a real-time telemetry recording session for a consented patient.',
  },
  'nav.explorer': {
    title: 'Session Explorer',
    description: 'Browse previously recorded sessions stored on this workstation, view or edit a session’s record, complete its post-session questionnaire, or load it into the analysis pages.',
  },
  'nav.spatial': {
    title: 'Spatial Analysis',
    description: 'A 3D reconstruction of the session’s head, controller and gaze geometry, with optional gaze-density heatmap and eye-movement scanpath overlays, scrubbed by the playback bar.',
  },
  'nav.insights': {
    title: 'Research Insights',
    description: 'Derived scientific measures across four domains computed from this session’s telemetry: cognitive load, vestibular/postural stability, motor kinematics, and physical exertion.',
  },
  'nav.quality': {
    title: 'Data Quality',
    description: 'Signal-integrity diagnostics for the loaded session: sampling stability, timing jitter, tracking dropouts, and per-channel validity.',
  },
  'nav.raw': {
    title: 'Raw Telemetry',
    description: 'A direct, frame-by-frame table of the recorded telemetry schema, unprocessed — for inspecting exactly what was written to the file.',
  },

  // ---------------------------------------------------------------------
  // Overview page (pages/Overview.tsx)
  // ---------------------------------------------------------------------

  'overview.sampling-stability': {
    title: 'Sampling Stability',
    description: 'Average telemetry sampling rate realized across the whole session, with σ (standard deviation), jitter and the largest single gap between two frame timestamps shown below it.',
    unit: 'Hz',
    provenance: 'derived',
    source: 'services/Series.ts — intervalStats() over frame timestamps',
    limitations: 'This is the realized recording rate, not necessarily the headset’s native refresh rate.',
  },
  'overview.positional-integrity': {
    title: 'Positional Integrity',
    description: 'Percentage of recorded frames where each tracked channel (HMD pose, binocular gaze, and controller pose when present) was reported valid by the VR runtime.',
    unit: '%',
    provenance: 'measured',
    limitations: 'A channel with no hardware connected (e.g. no controllers) is omitted from this list entirely rather than shown at 0%.',
  },
  'overview.signal-attrition': {
    title: 'Signal Attrition',
    description: 'Frames genuinely missing from the recorded file — detected from gaps in the recorder’s frame index, or taken directly from the session record when available. This counts frames that were never written, which is a different measurement from tracking-validity percentage: a frame can exist in the file and still be marked untracked.',
    unit: 'dropped frames',
    provenance: 'derived',
    source: 'services/Series.ts — bucketDrops() over frame_index gaps',
  },
  'overview.fixation-index': {
    title: 'Oculomotor Fixation Index',
    description: 'Percentage of frames classified as a fixation: head translational speed under 0.15 m/s while gaze tracking was valid. A head-motion-based proxy for visual fixation, not a true eye-velocity fixation detector.',
    unit: '%',
    provenance: 'derived',
    source: 'services/TelemetryParser.ts — processData()',
  },
  'overview.peak-saccade': {
    title: 'Peak Saccadic Velocity',
    description: 'Largest frame-to-frame change in left-eye gaze orientation recorded in the session, taken as the magnitude of the quaternion delta between consecutive valid gaze samples (×100 for a readable scale).',
    provenance: 'derived',
    source: 'services/TelemetryParser.ts — processData()',
    limitations: 'A relative measure of rotational gaze speed, not a calibrated degrees-per-second angular velocity — it isn’t normalized by elapsed time or converted from quaternion distance to a true rotation angle.',
  },
  'overview.head-speed': {
    title: 'Cervical Kinematic Mean',
    description: 'Average translational speed of the head-mounted display across the session, computed from frame-to-frame position deltas.',
    unit: 'm/s',
    provenance: 'derived',
  },
  'overview.hand-activity': {
    title: 'Bimanual Activity Index',
    description: 'Average translational speed of both VR controllers combined across the session, computed only from frames where a controller channel is present and tracked.',
    unit: 'm/s',
    provenance: 'derived',
    limitations: 'A session with no controller channel at all shows “No controller channels in this session” rather than 0 — the two mean different things.',
  },
  'overview.nasa-rtlx': {
    title: 'Cognitive Workload (NASA-RTLX)',
    description: 'Raw NASA Task Load Index score, self-reported by the participant after the session across six subscales (mental, physical and temporal demand, performance, effort, frustration).',
    unit: 'score, 0–100',
    provenance: 'reported',
    source: 'Post-session questionnaire',
    limitations: 'Subjective self-report, not a telemetry-derived measurement — unavailable until the questionnaire is completed.',
  },
  'overview.ssq-total': {
    title: 'Simulator Sickness (SSQ Total)',
    description: 'Total severity score from the 16-item Simulator Sickness Questionnaire, self-reported by the participant immediately after the session.',
    provenance: 'reported',
    source: 'Post-session questionnaire',
    limitations: 'Subjective self-report; unavailable until the questionnaire is completed.',
  },
  'overview.hr-baseline': {
    title: 'Cardiovascular Baseline',
    description: 'Mean heart rate across all frames with a valid reading from the connected physiological sensor.',
    unit: 'BPM',
    provenance: 'measured',
    limitations: 'Frames with no reading are excluded from the average rather than counted as a 0 BPM reading.',
  },
  'overview.ocular-integrity': {
    title: 'Ocular Sensor Integrity',
    description: 'Percentage of recorded frames where the headset’s binocular eye-tracking system reported a valid gaze sample.',
    unit: '%',
    provenance: 'measured',
  },
  'overview.provenance-legend': {
    title: 'Provenance Tags',
    description: 'DERIVED figures are computed by this app from raw telemetry. REPORTED figures are the participant’s own subjective questionnaire answers. MEASURED figures are direct sensor readings (or simple aggregates of one, like a mean or peak).',
  },

  // ---------------------------------------------------------------------
  // Eye Tracking page (pages/EyeTracking.tsx)
  // ---------------------------------------------------------------------

  'eye.validity': {
    title: 'Binocular Tracking Validity',
    description: 'Percentage of recorded frames where the headset’s eye-tracking system reported a valid binocular gaze sample.',
    unit: '%',
    provenance: 'measured',
  },
  'eye.gaze-mean': {
    title: 'Gaze Activity Mean',
    description: 'Average frame-to-frame change in left-eye gaze orientation across the session, taken as the magnitude of the quaternion delta between consecutive valid gaze samples (×100 for scale).',
    provenance: 'derived',
    limitations: 'A relative angular-velocity proxy, not a calibrated degrees-per-second measurement.',
  },
  'eye.peak-saccade': {
    title: 'Peak Saccade Intensity',
    description: 'Highest single-frame gaze-shift value recorded on this chart, with the time it occurred — the biggest apparent saccade in the session.',
    provenance: 'derived',
  },
  'eye.chart': {
    title: 'Saccadic Activity & Gaze Stability',
    description: 'Quaternion-delta-based gaze-shift magnitude over elapsed session time. Spikes indicate rapid eye movement (saccades); flat stretches indicate fixation.',
    provenance: 'derived',
    limitations: 'The Y axis is a relative, unitless intensity scaled for chart readability — not degrees per second.',
  },

  // ---------------------------------------------------------------------
  // Data Quality page (pages/DataQuality.tsx)
  // ---------------------------------------------------------------------

  'quality.overall-score': {
    title: 'Overall Quality Score',
    description: 'Composite score out of 100: HMD tracking validity (40% weight) + binocular gaze validity (40% weight) + a timing-jitter bonus (up to 20 points, reduced as average jitter increases).',
    unit: 'of 100',
    provenance: 'derived',
    limitations: 'A simple weighted heuristic for at-a-glance signal quality, not a validated research instrument.',
  },
  'quality.sampling': {
    title: 'Sampling Stability',
    description: 'Target frequency is this session’s average sampling rate. Average and maximum jitter are each frame’s deviation from the expected inter-frame interval (1 ÷ average rate), not from the empirical mean interval.',
    unit: 'Hz / ms',
    provenance: 'derived',
  },
  'quality.dropouts': {
    title: 'Signal Dropouts',
    description: 'Number of times tracking transitioned from valid to invalid during the session — counted as dropout events, not as a count of every invalid frame.',
    unit: 'events',
    provenance: 'derived',
  },
  'quality.completeness': {
    title: 'Data Completeness',
    description: 'Percentage of frames where HMD pose and binocular gaze were both valid at the same time — the frames usable for combined head+gaze analyses.',
    unit: '%',
    provenance: 'derived',
  },
  'quality.channel-validity': {
    title: 'Per-Channel Validity',
    description: 'Percentage of frames reporting a valid signal for this channel, computed only over frames where the channel is present in this session’s schema.',
    unit: '%',
    provenance: 'measured',
    limitations: 'A channel entirely absent from the recording (e.g. no controllers connected) is left out of this list rather than shown as 0% — absent and invalid are different diagnoses.',
  },

  // ---------------------------------------------------------------------
  // Physiology page (pages/Physiology.tsx)
  // ---------------------------------------------------------------------

  'physiology.hr': {
    title: 'Cardiovascular Response',
    description: 'Average and peak heart rate from the connected physiological sensor, across frames that carried a valid reading.',
    unit: 'BPM',
    provenance: 'measured',
    limitations: 'A frame with no reading (heart_rate_bpm ≤ 0) is excluded, not counted as 0 BPM.',
  },
  'physiology.head-velocity': {
    title: 'Motion Intensity (Head Velocity)',
    description: 'Average and peak translational speed of the head-mounted display, computed from frame-to-frame position deltas.',
    unit: 'm/s',
    provenance: 'derived',
    limitations: 'Values above 5 m/s are capped to 0 on the chart to suppress tracking-glitch spikes — a flat point at the cap should be read as “clamped,” not as a real pause in motion.',
  },
  'physiology.chart': {
    title: 'Movement vs. Cardiovascular Activity',
    description: 'Dual-axis view over elapsed session time: heart rate on the left axis (BPM, from the physiological sensor), head translational speed on the right axis (m/s, derived from HMD position).',
    provenance: 'derived',
  },

  // ---------------------------------------------------------------------
  // Research Insights page (pages/ResearchInsights.tsx / services/ScienceMetrics.ts)
  // ---------------------------------------------------------------------

  'insights.tepr-mean': {
    title: 'Mean TEPR (vs scene baseline)',
    description: 'Task-Evoked Pupillary Response: how far this session’s mean pupil diameter runs above the per-scene resting baseline (see Baseline Pupil Diameter). Pupil dilation above baseline is associated with cognitive effort.',
    unit: '%',
    provenance: 'derived',
    source: 'services/ScienceMetrics.ts — computeCognitiveLoad()',
    limitations: 'Pupil size also tracks scene brightness (the Pupillary Light Reflex). This telemetry schema has no ambient-light channel, so baselining is done per scene rather than globally as a best-effort, partial compensation — not a true PLR-corrected signal.',
  },
  'insights.tepr-peak': {
    title: 'Peak TEPR',
    description: 'Highest Task-Evoked Pupillary Response value reached during the session, with the time it occurred.',
    unit: '%',
    provenance: 'derived',
  },
  'insights.baseline-pupil': {
    title: 'Baseline Pupil Diameter',
    description: 'Mean binocular pupil size measured during the first 10 seconds of the session (or the first 20% of its duration, whichever is shorter), used as the session’s resting-baseline reference.',
    provenance: 'derived',
    limitations: 'Reported in the eye-tracking driver’s native pupil-size unit, which varies by headset/driver (some report a physical size, others a 0–1 confidence or blink-derived value) — compare only within the same session/hardware.',
  },
  'insights.cli-chart': {
    title: 'Cognitive Load Index Over Time',
    description: 'Per-scene-baselined pupil dilation (TEPR) rescaled onto a 0–100 display band for chart readability.',
    provenance: 'derived',
    limitations: 'The 0–100 scaling is a display convenience (TEPR × 4, clamped), not a validated clinical cognitive-load index.',
  },
  'insights.sway-path': {
    title: 'Total Sway Path Length',
    description: 'Total horizontal (X/Z-plane) distance traveled by the head-mounted display across the session — a standard posturography measure of head sway.',
    unit: 'm',
    provenance: 'derived',
    source: 'services/ScienceMetrics.ts — computePosturalStability()',
    limitations: 'Frame-to-frame jumps larger than 0.5 m are excluded as likely teleport/recenter events rather than real movement.',
  },
  'insights.sway-velocity': {
    title: 'Mean Sway Velocity',
    description: 'Average horizontal (X/Z-plane) head displacement rate across the session.',
    unit: 'm/s',
    provenance: 'derived',
  },
  'insights.sway-ellipse': {
    title: '95% Sway Ellipse Area',
    description: 'Area of the ellipse containing the central 95% of the head’s horizontal position samples during the session — a standard posturography confidence-ellipse method. A larger area indicates more postural sway.',
    unit: 'm²',
    provenance: 'derived',
    source: 'Prieto et al., 1996 (cited in services/ScienceMetrics.ts)',
  },
  'insights.low-freq-energy': {
    title: 'Low-Freq (<0.5Hz) Energy',
    description: 'Share of the head-sway-speed signal’s spectral energy found below 0.5 Hz, from a discrete Fourier transform of the sway-velocity series over the session.',
    unit: '%',
    provenance: 'derived',
    source: 'Munafo et al., 2017 (cited in services/ScienceMetrics.ts)',
    limitations: 'A low-frequency-dominant pattern is an early-warning indicator the cybersickness literature associates with rising visually-induced motion sickness risk — not a diagnosis.',
  },
  'insights.sway-chart': {
    title: 'Head Sway Velocity',
    description: 'Planar (X/Z) head displacement rate over elapsed session time.',
    unit: 'm/s',
    provenance: 'derived',
  },
  'insights.risk-chart': {
    title: 'Cybersickness Risk Trend',
    description: 'Windowed sway-velocity intensity across the session, normalized 0–100 against this session’s own peak window.',
    provenance: 'derived',
    limitations: 'Relative to this session only — not comparable across different sessions or subjects.',
  },
  'insights.jerk': {
    title: 'Normalized Jerk',
    description: 'Dimensionless movement-smoothness index for this hand’s controller motion, computed from the rate of change of acceleration (jerk) integrated over the movement and normalized for duration and path length. Lower is smoother.',
    provenance: 'derived',
    source: 'Hogan & Sternad, 2009 (cited in services/ScienceMetrics.ts)',
    limitations: 'Only meaningful compared within the same session/task — not across different sessions.',
  },
  'insights.symmetry': {
    title: 'Bilateral Symmetry Index',
    description: 'Asymmetry between left and right hand: |left − right| ÷ (left + right), as a percentage. 0% is perfectly symmetric bilateral use.',
    unit: '% asymmetry',
    provenance: 'derived',
  },
  'insights.peak-reach': {
    title: 'Peak Reach',
    description: 'Maximum recorded distance between this hand’s controller and the HMD during the session — a head-centered proxy for reach distance, sanity-bounded under 2 m to reject tracking outliers. Shown as a percentage of the subject’s calibrated arm length when that measurement is recorded for this session.',
    unit: 'm',
    provenance: 'derived',
    limitations: 'Not corrected for head yaw, so it measures straight-line distance rather than a body-relative reach direction.',
  },
  'insights.bimanual-chart': {
    title: 'Bimanual Controller Speed',
    description: 'Left vs. right controller translational speed over elapsed session time.',
    unit: 'm/s',
    provenance: 'derived',
  },
  'insights.resting-hr': {
    title: 'Resting HR Estimate',
    description: 'Mean heart rate over the first 3–10 seconds of the session (first 20% of duration, bounded to that range), used as a per-session baseline for drift and exertion calculations.',
    unit: 'BPM',
    provenance: 'measured',
  },
  'insights.peak-hr': {
    title: 'Peak HR',
    description: 'Highest heart-rate reading recorded during the session.',
    unit: 'BPM',
    provenance: 'measured',
  },
  'insights.hr-drift': {
    title: 'Cardiovascular Drift',
    description: 'Difference in mean heart rate between the second half and first half of the session, and that difference expressed as a rate per minute.',
    unit: 'BPM',
    provenance: 'derived',
    limitations: 'Classic drift analysis assumes constant workload throughout — a free-form VR session may not satisfy that, so treat the rate as indicative rather than clinical.',
  },
  'insights.exertion-index': {
    title: 'Composite Exertion Index',
    description: 'Score from 0–100 blending heart-rate elevation above the resting baseline (60% weight) and normalized movement intensity (40% weight).',
    unit: 'of 100',
    provenance: 'derived',
    limitations: 'A simple heuristic, not a validated physiological exertion instrument.',
  },
  'insights.exertion-chart': {
    title: 'Heart Rate vs. Movement Intensity',
    description: 'Cross-modal view of cardiovascular response (BPM, left axis) and movement intensity (right axis) over elapsed session time.',
    provenance: 'derived',
  },

  // ---------------------------------------------------------------------
  // Metadata page (pages/Metadata.tsx)
  // ---------------------------------------------------------------------

  'metadata.timestamp': {
    title: 'Timestamp (ns)',
    description: 'Recording timestamp for this frame, in nanoseconds, from an internal recorder reference clock.',
    unit: 'ns',
    provenance: 'raw',
    limitations: 'Not a wall-clock/UTC timestamp — it’s only meaningful as a difference from another timestamp in the same session.',
  },
  'metadata.sensor-detection': {
    title: 'Hardware Capabilities Detected',
    description: 'A sensor shows DETECTED when this session’s recorded schema includes the data channel associated with it.',
    provenance: 'raw',
    limitations: '“NOT AVAILABLE” means the channel is absent from this file — it does not mean the sensor failed during recording; that channel was simply never part of this session’s data.',
  },

  // ---------------------------------------------------------------------
  // Raw Data Explorer (pages/RawDataExplorer.tsx)
  // ---------------------------------------------------------------------

  'raw.frame-index': {
    title: 'Frame Index',
    description: 'Sequential position of this frame within the raw recorded stream. A gap between successive values means one or more frames were dropped during recording.',
    provenance: 'raw',
  },
  'raw.timestamp': {
    title: 'Timestamp (ns)',
    description: 'Recording timestamp for this frame, in nanoseconds, from an internal recorder reference clock — not wall-clock/UTC time.',
    unit: 'ns',
    provenance: 'raw',
  },
  'raw.hmd-pos': {
    title: 'HMD Position (X / Y / Z)',
    description: 'Head-mounted display position along this axis of the tracking space, as reported by the VR runtime. Y is treated as the vertical (up) axis elsewhere in this app.',
    unit: 'm',
    provenance: 'device',
  },
  'raw.hmd-valid': {
    title: 'HMD Valid',
    description: 'Whether the VR runtime reported a valid, tracked HMD pose for this frame (TRUE) or lost tracking (FALSE).',
    provenance: 'device',
  },
  'raw.hr': {
    title: 'HR (BPM)',
    description: 'Heart rate reported by the connected physiological sensor for this frame.',
    unit: 'BPM',
    provenance: 'device',
    limitations: 'A value of 0 means no reading was available for that frame, not an actual heart rate of zero.',
  },

  // ---------------------------------------------------------------------
  // Spatial Viewer (components/visualizations/SpatialViewer.tsx)
  // ---------------------------------------------------------------------

  'spatial.heatmap': {
    title: 'Volumetric Heatmap',
    description: 'A 3D voxel-grid visualization of where the participant’s binocular gaze converged in space across the session. Voxel color and size encode how much gaze time accumulated in that region.',
    provenance: 'derived',
    limitations: 'Reflects accumulated estimated gaze convergence, not a physical property of the space itself.',
  },
  'spatial.scanpath': {
    title: 'Oculomotor Scanpath',
    description: 'The sequence of estimated gaze-convergence points connected in chronological order, with markers at points classified as fixations (consecutive gaze-orientation samples that changed by less than a small threshold).',
    provenance: 'derived',
    limitations: 'A qualitative visualization of gaze movement order, not a validated fixation/saccade classifier.',
  },
  'spatial.por': {
    title: 'Live Point of Regard',
    description: 'Estimated 3D point where the participant’s left and right gaze rays converge at the current playback frame, found from the closest approach between the two eye rays.',
    provenance: 'derived',
    limitations: 'When the gaze rays are nearly parallel (looking far into the distance), the point is instead projected a fixed 2 m ahead along the average gaze direction — an estimate from ray geometry, not a hardware depth measurement.',
  },

  // ---------------------------------------------------------------------
  // New Session / Live Acquisition (pages/NewSession.tsx)
  // ---------------------------------------------------------------------

  'session.backend': {
    title: 'Runtime Backend',
    description: 'The VR tracking API this session’s telemetry engine reads from. Auto-Detect probes the available backends; OpenXR is the cross-vendor standard API; Oculus and SteamVR are vendor-specific APIs for Meta and Valve/HTC runtimes respectively.',
    provenance: 'raw',
    limitations: 'Which options actually work depends on the VR runtime and headset installed on this machine.',
  },

  // ---------------------------------------------------------------------
  // Post-Session Questionnaire (components/PostSessionQuestionnaire.tsx)
  // ---------------------------------------------------------------------

  'questionnaire.ssq': {
    title: 'Simulator Sickness Questionnaire',
    description: 'A standardized 16-symptom self-report questionnaire, completed by the participant right after the session. Each symptom is rated None to Severe; responses are combined into nausea, oculomotor and disorientation subscale scores plus a total severity score on submission.',
    provenance: 'reported',
  },
  'questionnaire.tlx': {
    title: 'NASA Task Load Index',
    description: 'A standardized workload self-report: the participant rates six subscales — mental, physical and temporal demand, performance, effort, and frustration — each 0–100. Combined into a single Raw TLX score on submission.',
    provenance: 'reported',
  },
};
