// src/frontend/VRTelemetry/src/components/PostSessionQuestionnaire.tsx
//
// The one piece of subjective data collection this app never had a UI for:
// session_metadata has always had columns for SSQ/NASA-TLX subscales and
// perceived temperature, but nothing populated them until this form existed
// (see src/analytics/questionnaires.py for the scoring it submits to).

import React, { useState } from 'react';
import { X, ClipboardList, AlertCircle, Loader2, CheckCircle2 } from 'lucide-react';
import { InfoTooltip } from './InfoTooltip';

interface PostSessionQuestionnaireProps {
  sessionId: string;
  onClose: () => void;
  onSaved: () => void;
}

const SSQ_ITEMS: { key: string; label: string }[] = [
  { key: 'general_discomfort', label: 'General discomfort' },
  { key: 'fatigue', label: 'Fatigue' },
  { key: 'headache', label: 'Headache' },
  { key: 'eye_strain', label: 'Eye strain' },
  { key: 'difficulty_focusing', label: 'Difficulty focusing' },
  { key: 'increased_salivation', label: 'Increased salivation' },
  { key: 'sweating', label: 'Sweating' },
  { key: 'nausea', label: 'Nausea' },
  { key: 'difficulty_concentrating', label: 'Difficulty concentrating' },
  { key: 'fullness_of_head', label: 'Fullness of head' },
  { key: 'blurred_vision', label: 'Blurred vision' },
  { key: 'dizziness_eyes_open', label: 'Dizziness (eyes open)' },
  { key: 'dizziness_eyes_closed', label: 'Dizziness (eyes closed)' },
  { key: 'vertigo', label: 'Vertigo' },
  { key: 'stomach_awareness', label: 'Stomach awareness' },
  { key: 'burping', label: 'Burping' },
];
const SSQ_SEVERITY_LABELS = ['None', 'Slight', 'Moderate', 'Severe'];

const TLX_ITEMS: { key: string; label: string; lowAnchor: string; highAnchor: string }[] = [
  { key: 'mental_demand', label: 'Mental Demand', lowAnchor: 'Very Low', highAnchor: 'Very High' },
  { key: 'physical_demand', label: 'Physical Demand', lowAnchor: 'Very Low', highAnchor: 'Very High' },
  { key: 'temporal_demand', label: 'Temporal Demand', lowAnchor: 'Very Low', highAnchor: 'Very High' },
  { key: 'performance', label: 'Performance', lowAnchor: 'Perfect', highAnchor: 'Failure' },
  { key: 'effort', label: 'Effort', lowAnchor: 'Very Low', highAnchor: 'Very High' },
  { key: 'frustration', label: 'Frustration', lowAnchor: 'Very Low', highAnchor: 'Very High' },
];

const THERMAL_OPTIONS = [
  { value: 'cold', label: 'Cold' },
  { value: 'cool', label: 'Cool' },
  { value: 'slightly_cool', label: 'Slightly Cool' },
  { value: 'neutral', label: 'Neutral' },
  { value: 'slightly_warm', label: 'Slightly Warm' },
  { value: 'warm', label: 'Warm' },
  { value: 'hot', label: 'Hot' },
];

export const PostSessionQuestionnaire: React.FC<PostSessionQuestionnaireProps> = ({ sessionId, onClose, onSaved }) => {
  const [ssq, setSsq] = useState<Record<string, number>>({});
  const [tlx, setTlx] = useState<Record<string, number>>({});
  const [thermalComfort, setThermalComfort] = useState('');
  const [perceivedTempC, setPerceivedTempC] = useState('');
  const [sessionRating, setSessionRating] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ ssq: any; nasa_tlx: any } | null>(null);

  const handleSubmit = async () => {
    setIsSaving(true);
    setError(null);
    try {
      const body: Record<string, any> = { ...ssq, ...tlx };
      if (thermalComfort) body.thermal_comfort = thermalComfort;
      if (perceivedTempC !== '') body.perceived_temp_c = Number(perceivedTempC);
      if (sessionRating !== '') body.session_rating = Number(sessionRating);

      const res = await fetch(`http://localhost:8000/api/sessions/${sessionId}/questionnaire`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to save questionnaire.');
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error.');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="questionnaire-title">
      <div className="modal-card flex max-w-2xl flex-col overflow-hidden p-0">
        <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: '1px solid var(--hair)' }}>
          <div className="flex items-center gap-2">
            <ClipboardList className="h-[18px] w-[18px]" style={{ color: 'var(--s1)' }} />
            <h2 id="questionnaire-title" className="m-0 text-[16px] font-semibold">Post-Session Questionnaire</h2>
          </div>
          <button onClick={onClose} aria-label="Close questionnaire" className="btn-ghost">
            <X className="h-[18px] w-[18px]" />
          </button>
        </div>

        {result ? (
          <div className="flex flex-col items-center gap-3 p-8 text-center">
            <CheckCircle2 className="h-10 w-10" style={{ color: 'var(--s6)' }} />
            <p className="m-0 text-[14px] font-medium">Questionnaire saved.</p>
            <div className="mono space-y-1 text-[12px] text-ink-3">
              <p>SSQ Total Severity: {result.ssq.ssq_total_severity} ({result.ssq.ssq_severity_band})</p>
              <p>NASA-TLX (RTLX): {result.nasa_tlx.nasa_tlx_rtlx} ({result.nasa_tlx.nasa_tlx_band} workload)</p>
            </div>
            <button onClick={onSaved} className="btn-accent mt-2">Done</button>
          </div>
        ) : (
          <>
            <div className="flex-1 space-y-5 overflow-y-auto p-5">
              {error && (
                <div className="notice tone-2 items-start text-[13px]">
                  <AlertCircle className="mt-0.5 h-4 w-4 flex-none text-tone" /><p>{error}</p>
                </div>
              )}

              <fieldset>
                <legend className="section-title mb-1.5 flex items-center gap-1">
                  Simulator Sickness Questionnaire <InfoTooltip id="questionnaire.ssq" />
                </legend>
                <p className="mb-3 text-[12px] text-ink-3">Rate how much each symptom applies right now.</p>
                <div className="well space-y-2 p-3.5">
                  {SSQ_ITEMS.map(item => (
                    <div key={item.key} className="flex items-center justify-between gap-4">
                      <label htmlFor={`ssq-${item.key}`} className="flex-1 text-[13px] text-ink-2">{item.label}</label>
                      <div id={`ssq-${item.key}`} role="radiogroup" aria-label={item.label} className="flex gap-1">
                        {SSQ_SEVERITY_LABELS.map((severityLabel, level) => (
                          <button
                            key={level}
                            type="button"
                            role="radio"
                            aria-checked={ssq[item.key] === level}
                            title={severityLabel}
                            onClick={() => setSsq({ ...ssq, [item.key]: level })}
                            className="mono h-8 w-8 flex-none rounded-lg border-none text-[11px] transition-all"
                            style={ssq[item.key] === level
                              ? { background: 'linear-gradient(145deg, var(--act-a), var(--act-b))', color: '#fff', boxShadow: 'var(--act-glow)' }
                              : { background: 'var(--well)', color: 'var(--ink-3)', boxShadow: 'var(--clay-press)' }}
                          >
                            {level}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </fieldset>

              <fieldset className="pt-4" style={{ borderTop: '1px solid var(--hair)' }}>
                <legend className="section-title mb-1.5 flex items-center gap-1">
                  NASA Task Load Index <InfoTooltip id="questionnaire.tlx" />
                </legend>
                <p className="mb-3 text-[12px] text-ink-3">Drag each slider between the two anchors.</p>
                <div className="well space-y-4 p-3.5">
                  {TLX_ITEMS.map(item => (
                    <div key={item.key}>
                      <label htmlFor={`tlx-${item.key}`} className="mb-1.5 flex justify-between text-[13px] text-ink-2">
                        <span>{item.label}</span>
                        <span className="mono text-ink-3">{tlx[item.key] ?? 0}</span>
                      </label>
                      <div className="flex items-center gap-2">
                        <span className="w-16 text-right text-[10px] text-ink-3">{item.lowAnchor}</span>
                        <input
                          id={`tlx-${item.key}`}
                          type="range"
                          min={0}
                          max={100}
                          value={tlx[item.key] ?? 0}
                          onChange={e => setTlx({ ...tlx, [item.key]: Number(e.target.value) })}
                          className="scrub flex-1" style={{ ['--pct' as string]: `${tlx[item.key] ?? 0}%` }}
                        />
                        <span className="w-16 text-[10px] text-ink-3">{item.highAnchor}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </fieldset>

              <fieldset className="grid grid-cols-1 gap-4 pt-4 sm:grid-cols-3" style={{ borderTop: '1px solid var(--hair)' }}>
                <legend className="sr-only">Session context</legend>
                <div>
                  <label htmlFor="thermal-comfort" className="field-label">Thermal Comfort</label>
                  <select
                    id="thermal-comfort"
                    value={thermalComfort}
                    onChange={e => setThermalComfort(e.target.value)}
                    className="field"
                  >
                    <option value="">Not reported</option>
                    {THERMAL_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </div>
                <div>
                  <label htmlFor="perceived-temp" className="field-label">Room Temp (°C)</label>
                  <input
                    id="perceived-temp"
                    type="number"
                    step="0.5"
                    value={perceivedTempC}
                    onChange={e => setPerceivedTempC(e.target.value)}
                    className="field"
                  />
                </div>
                <div>
                  <label htmlFor="session-rating" className="field-label">Overall Rating (0-10)</label>
                  <input
                    id="session-rating"
                    type="number"
                    min={0}
                    max={10}
                    value={sessionRating}
                    onChange={e => setSessionRating(e.target.value)}
                    className="field"
                  />
                </div>
              </fieldset>
            </div>
            <div className="flex justify-end gap-2 px-5 py-4" style={{ borderTop: '1px solid var(--hair)' }}>
              <button onClick={onClose} className="btn-clay">Cancel</button>
              <button
                onClick={handleSubmit}
                disabled={isSaving}
                className="btn-accent"
              >
                {isSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : <ClipboardList className="w-4 h-4" />}
                {isSaving ? 'Scoring & Saving...' : 'Submit Questionnaire'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};
