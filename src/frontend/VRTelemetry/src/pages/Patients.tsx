import { useEffect, useState } from 'react';
import { Plus, Edit2, Save, Trash2, ShieldCheck, ShieldOff, ShieldPlus, X, AlertCircle, Database, Search } from 'lucide-react';
import { ParticipantConsentFlow, type ConsentSubmission, type RecordedConsent } from '../components/ParticipantConsentFlow';

const API = 'http://localhost:8000';

type WithdrawalScope = 'ALL_DELETE' | 'FUTURE_ONLY' | 'PROVIDER_RESEARCH_ONLY';

const WITHDRAWAL_OPTIONS: { scope: WithdrawalScope; title: string; body: string }[] = [
  {
    scope: 'ALL_DELETE',
    title: 'Stop taking part and delete all my data',
    body: 'Your profile, recordings and results linked to you will be permanently deleted from this computer and '
      + 'the central server, including any optional copy held by the software provider. Results that have already '
      + 'been made anonymous or published as group statistics cannot be removed.',
  },
  {
    scope: 'FUTURE_ONLY',
    title: 'Stop future recordings only',
    body: 'No new recordings will be made. Data collected before today stays in the study under the consent you '
      + 'gave earlier. You can still ask for deletion later.',
  },
  {
    scope: 'PROVIDER_RESEARCH_ONLY',
    title: 'Withdraw only the optional research use by the software provider',
    body: "The provider's copy of your data will be deleted. Your participation in the study continues.",
  },
];

interface Patient {
  patient_id: string;
  display_name: string;
  external_ref: string;
  date_of_birth: string;
  biological_sex: string;
  notes: string;
  gdpr_consent_given: number;
  gdpr_consent_version: string;
  gdpr_consent_timestamp: string;
  gdpr_consent_withdrawn_at: string | null;
  is_anonymized: number;
  created_at: string;
  age_years: number | null;
  height_cm: number | null;
  weight_kg: number | null;
  dominant_hand: string | null;
  vr_experience_level: string | null;
  vr_experience_hours_estimate: number | null;
  gaming_experience_hours_per_week: number | null;
  vision_correction: string | null;
  vision_impairment: string | null;
  motion_sickness_susceptibility: string | null;
  relevant_health_conditions: string | null;
}

const emptyForm = {
  display_name: '',
  external_ref: '',
  date_of_birth: '',
  biological_sex: '',
  notes: '',
  age_years: '',
  height_cm: '',
  weight_kg: '',
  dominant_hand: '',
  vr_experience_level: '',
  vr_experience_hours_estimate: '',
  gaming_experience_hours_per_week: '',
  vision_correction: '',
  vision_impairment: '',
  motion_sickness_susceptibility: '',
  relevant_health_conditions: '',
};

// Fields captured once per patient as a self-reported health/demographic
// profile. Numeric fields are kept as strings in form state (for free text
// editing) and coerced to number|null right before hitting the API.
const HEALTH_NUMERIC_FIELDS = [
  'age_years',
  'height_cm',
  'weight_kg',
  'vr_experience_hours_estimate',
  'gaming_experience_hours_per_week',
] as const;

const numOrNull = (v: unknown): number | null => {
  if (v === '' || v === null || v === undefined) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

const buildPatientPayload = (form: Record<string, any>) => {
  const payload: Record<string, any> = { ...form };
  for (const field of HEALTH_NUMERIC_FIELDS) {
    if (field in payload) payload[field] = numOrNull(payload[field]);
  }
  return payload;
};

export const Patients = () => {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState(emptyForm);
  const [createError, setCreateError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<'all' | 'consented' | 'withdrawn'>('all');

  // The participant consent flow (GDPR-09): for a new patient, or a new consent
  // for an existing one (new study, new wording, or after a withdrawal).
  const [consentFlow, setConsentFlow] = useState<null | { mode: 'create' } | { mode: 'reconsent'; patient: Patient }>(null);

  const [editing, setEditing] = useState<Patient | null>(null);
  const [editForm, setEditForm] = useState<Record<string, any>>({});

  const fetchPatients = async () => {
    setIsLoading(true);
    try {
      const res = await fetch('http://localhost:8000/api/patients');
      if (!res.ok) throw new Error('Failed to load patient registry.');
      setPatients(await res.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => { fetchPatients(); }, []);

  const handleCreate = async () => {
    setCreateError(null);
    if (!createForm.display_name.trim()) {
      setCreateError('Display name is required.');
      return;
    }
    // Nothing is stored yet. The record is created only together with the
    // participant's own consent, in one request, at the end of the flow.
    setConsentFlow({ mode: 'create' });
  };

  const submitNewPatient = async (consent: ConsentSubmission): Promise<RecordedConsent> => {
    setIsSaving(true);
    try {
      const res = await fetch(`${API}/api/patients`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...buildPatientPayload(createForm), consent }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to create patient.');
      return data.consent as RecordedConsent;
    } finally {
      setIsSaving(false);
    }
  };

  const submitReconsent = (patientId: string) => async (consent: ConsentSubmission): Promise<RecordedConsent> => {
    const res = await fetch(`${API}/api/patients/${patientId}/consents`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(consent),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed to record consent.');
    return data as RecordedConsent;
  };

  const closeConsentFlow = (recorded: RecordedConsent | null) => {
    if (recorded && consentFlow?.mode === 'create') {
      setShowCreate(false);
      setCreateForm(emptyForm);
    }
    setConsentFlow(null);
    fetchPatients();
  };

  const openEdit = (p: Patient) => {
    setEditing(p);
    setEditForm({
      display_name: p.display_name,
      external_ref: p.external_ref,
      date_of_birth: p.date_of_birth,
      biological_sex: p.biological_sex,
      notes: p.notes,
      age_years: p.age_years ?? '',
      height_cm: p.height_cm ?? '',
      weight_kg: p.weight_kg ?? '',
      dominant_hand: p.dominant_hand ?? '',
      vr_experience_level: p.vr_experience_level ?? '',
      vr_experience_hours_estimate: p.vr_experience_hours_estimate ?? '',
      gaming_experience_hours_per_week: p.gaming_experience_hours_per_week ?? '',
      vision_correction: p.vision_correction ?? '',
      vision_impairment: p.vision_impairment ?? '',
      motion_sickness_susceptibility: p.motion_sickness_susceptibility ?? '',
      relevant_health_conditions: p.relevant_health_conditions ?? '',
    });
  };

  const [sessionsFor, setSessionsFor] = useState<{ patient: Patient; sessions: any[] } | null>(null);
  const handleViewSessions = async (patientId: string) => {
  const res = await fetch(`http://localhost:8000/api/patients/${patientId}/sessions`);
    if (res.ok) setSessionsFor(await res.json());
    };

  const handleSaveEdit = async () => {
    if (!editing) return;
    try {
      const res = await fetch(`http://localhost:8000/api/patients/${editing.patient_id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildPatientPayload(editForm)),
      });
      if (!res.ok) throw new Error('Failed to save changes.');
      setEditing(null);
      fetchPatients();
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Failed to save.');
    }
  };

  // Withdrawal (Art. 7(3) GDPR): the participant chooses the scope (GDPR-10).
  const [withdrawFor, setWithdrawFor] = useState<Patient | null>(null);
  const [withdrawScope, setWithdrawScope] = useState<WithdrawalScope>('FUTURE_ONLY');
  const [withdrawError, setWithdrawError] = useState<string | null>(null);

  const handleWithdrawConsent = (patientId: string) => {
    setWithdrawFor(patients.find(p => p.patient_id === patientId) ?? null);
    setWithdrawScope('FUTURE_ONLY');
    setWithdrawError(null);
  };

  const confirmWithdrawal = async () => {
    if (!withdrawFor) return;
    setWithdrawError(null);
    const res = await fetch(`${API}/api/patients/${withdrawFor.patient_id}/withdraw-consent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope: withdrawScope }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setWithdrawError(data.detail || 'The withdrawal could not be recorded.');
      return;
    }
    setWithdrawFor(null);
    fetchPatients();
  };

  const handleErase = async (patientId: string) => {
    if (!confirm(
      'Erase this participant? This permanently deletes their profile, recordings and all derived results from this ' +
      'workstation and the central server. The consent and withdrawal record is kept as proof, as required by law. ' +
      'This cannot be undone.'
    )) return;
    const res = await fetch(`${API}/api/patients/${patientId}`, { method: 'DELETE' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      alert(typeof data.detail === 'string' ? data.detail : 'The erasure could not be completed.');
    } else if (data.erasure && !data.erasure.hub_confirmed) {
      alert(
        `Erased on this workstation (${data.erasure.sessions} session(s), ${data.erasure.files_deleted} file(s)). ` +
        'The central server could not be reached; its copies will be deleted automatically when it is.'
      );
    }
    fetchPatients();
  };

  // An erased record is neither "consented" nor "withdrawn" — it has no consent
  // state left to speak of — so it gets its own count rather than inflating either.
  const counts = {
    total: patients.length,
    consented: patients.filter(p => p.gdpr_consent_given && !p.is_anonymized).length,
    withdrawn: patients.filter(p => !p.gdpr_consent_given && !p.is_anonymized).length,
    erased: patients.filter(p => p.is_anonymized).length,
  };

  const q = query.trim().toLowerCase();
  const visible = patients.filter(p => {
    if (filter === 'consented' && !(p.gdpr_consent_given && !p.is_anonymized)) return false;
    if (filter === 'withdrawn' && !(!p.gdpr_consent_given && !p.is_anonymized)) return false;
    if (!q) return true;
    return (p.display_name || '').toLowerCase().includes(q)
      || (p.external_ref || '').toLowerCase().includes(q);
  });

  return (
    <div className="mx-auto flex max-w-[1360px] flex-col gap-4">

      <div className="flex items-end justify-between gap-6">
        <div>
          <h1 className="page-title">Patient Registry</h1>
          <p className="page-sub" style={{ maxWidth: '88ch' }}>
            Durable subject identities used across recording sessions. GDPR consent is required and logged for every
            record. Self-reported health &amp; demographic profile is captured once and auto-populates every
            session's telemetry metadata.
          </p>
        </div>
        <button className="btn-accent flex-none" onClick={() => setShowCreate(true)}>
          <Plus className="h-4 w-4" /> New Patient
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-4">
        <div className="clay p-3.5">
          <div className="stat-label mb-1.5">Registered subjects</div>
          <div className="stat-value">{counts.total}</div>
        </div>
        <div className="clay p-3.5">
          <div className="stat-label mb-1.5">Consent active</div>
          <div className="stat-value" style={{ color: 'var(--s6)' }}>{counts.consented}</div>
        </div>
        <div className="clay p-3.5" style={{ borderLeft: '3px solid var(--s4)' }}>
          <div className="stat-label mb-1.5">Withdrawn</div>
          <div className="stat-value" style={{ color: 'var(--s4)' }}>{counts.withdrawn}</div>
        </div>
        <div className="clay p-3.5">
          <div className="stat-label mb-1.5">Erased</div>
          <div className="stat-value text-ink-3">{counts.erased}</div>
        </div>
      </div>

      <div className="clay flex flex-col gap-3 p-3.5">
        <div className="flex flex-wrap items-center gap-3">
          <div className="clay-press flex max-w-[340px] flex-1 items-center gap-2 px-3 py-[7px]" style={{ borderRadius: 11 }}>
            <Search className="h-4 w-4 flex-none text-ink-3" aria-hidden="true" />
            <label htmlFor="patient-search" className="sr-only">Search patients</label>
            <input
              id="patient-search"
              placeholder="Search name or external ref"
              value={query}
              onChange={e => setQuery(e.target.value)}
              className="min-w-0 flex-1 border-none bg-transparent text-[13px] outline-none"
            />
          </div>
          <div className="seg" role="group" aria-label="Filter by consent state">
            {(['all', 'consented', 'withdrawn'] as const).map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                aria-pressed={filter === f}
                className={filter === f ? 'seg-item is-active' : 'seg-item'}
              >
                {f === 'all' ? 'All' : f === 'consented' ? 'Consented' : 'Withdrawn'}
              </button>
            ))}
          </div>
        </div>

        <div className="well overflow-hidden" style={{ borderRadius: 12 }}>
          {isLoading ? (
            <p className="py-10 text-center text-[13px] text-ink-3">Loading registry…</p>
          ) : error ? (
            <div className="flex flex-col items-center gap-2 py-10" style={{ color: 'var(--s2)' }}>
              <AlertCircle className="h-7 w-7" />
              <p className="m-0 text-[13px] font-medium">{error}</p>
            </div>
          ) : patients.length === 0 ? (
            <p className="py-10 text-center text-[13px] text-ink-3">No patients yet. Create one to enable recording.</p>
          ) : visible.length === 0 ? (
            <p className="py-10 text-center text-[13px] text-ink-3">No patients match this search or filter.</p>
          ) : (
            <div className="max-h-[52vh] overflow-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>External Ref</th>
                    <th>DOB</th>
                    <th>Age</th>
                    <th>Height / Weight</th>
                    <th>VR Experience</th>
                    <th>GDPR Consent</th>
                    <th style={{ textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map(p => (
                    <tr key={p.patient_id} style={p.is_anonymized ? { opacity: 0.6 } : undefined}>
                      <td style={{ color: 'var(--ink)', fontWeight: 500 }}>
                        {p.is_anonymized
                          ? <span className="italic text-ink-3">Erased record</span>
                          : p.display_name}
                      </td>
                      <td className="num text-ink-3">{p.external_ref || '—'}</td>
                      <td className="num">{p.date_of_birth || '—'}</td>
                      <td className="num">{p.age_years ?? '—'}</td>
                      <td className="num">
                        {p.height_cm || p.weight_kg
                          ? [p.height_cm ? `${p.height_cm} cm` : null, p.weight_kg ? `${p.weight_kg} kg` : null].filter(Boolean).join(' / ')
                          : '—'}
                      </td>
                      <td>
                        {p.vr_experience_level || '—'}{p.vr_experience_hours_estimate ? ` (${p.vr_experience_hours_estimate}h)` : ''}
                      </td>
                      <td>
                        {p.is_anonymized ? (
                          <span className="chip" style={{ color: 'var(--ink-3)', background: 'var(--well-grid)' }}>Erased</span>
                        ) : p.gdpr_consent_given ? (
                          <span className="chip tone-6">
                            <ShieldCheck className="h-3.5 w-3.5" /> Active v{p.gdpr_consent_version}
                          </span>
                        ) : (
                          <span className="chip tone-4">
                            <ShieldOff className="h-3.5 w-3.5" /> Withdrawn
                          </span>
                        )}
                      </td>
                      <td>
                        <div className="flex justify-end gap-1.5">
                          {!p.is_anonymized && (
                            <>
                              <button onClick={() => handleViewSessions(p.patient_id)} aria-label="View recorded sessions" title="View recorded sessions" className="btn-ghost">
                                <Database className="h-4 w-4" />
                              </button>
                              <button onClick={() => openEdit(p)} aria-label="Edit patient" title="Edit patient" className="btn-ghost" style={{ color: 'var(--s1)' }}>
                                <Edit2 className="h-4 w-4" />
                              </button>
                              {p.gdpr_consent_given === 1 ? (
                                <button onClick={() => handleWithdrawConsent(p.patient_id)} aria-label="Withdraw consent" title="Withdraw consent" className="btn-ghost" style={{ color: 'var(--s4)' }}>
                                  <ShieldOff className="h-4 w-4" />
                                </button>
                              ) : (
                                <button onClick={() => setConsentFlow({ mode: 'reconsent', patient: p })} aria-label="Record new consent" title="Record new consent (participant)" className="btn-ghost" style={{ color: 'var(--s6)' }}>
                                  <ShieldPlus className="h-4 w-4" />
                                </button>
                              )}
                              <button onClick={() => handleErase(p.patient_id)} aria-label="Erase patient data (GDPR right to erasure)" title="Erase (GDPR right to erasure)" className="btn-ghost" style={{ color: 'var(--s2)' }}>
                                <Trash2 className="h-4 w-4" />
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <p className="m-0 text-[11.5px] text-ink-3">
          Erasure permanently deletes the participant's profile, recordings, logs and results here and on the central
          server, and cannot be undone. The consent record is kept as proof.
        </p>
      </div>

      {/* Create Modal */}
      {showCreate && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="create-patient-title">
          <div className="modal-card flex max-w-lg flex-col overflow-hidden p-0">
            <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: '1px solid var(--hair)' }}>
              <h2 id="create-patient-title" className="m-0 text-[16px] font-semibold">New Patient</h2>
              <button onClick={() => setShowCreate(false)} aria-label="Close new patient form" className="btn-ghost">
                <X className="h-[18px] w-[18px]" />
              </button>
            </div>
            <div className="space-y-4 overflow-y-auto px-5 py-5">
              {createError && (
                <div className="notice tone-2 items-start text-[13px]">
                  <AlertCircle className="mt-0.5 h-4 w-4 flex-none text-tone" /><p>{createError}</p>
                </div>
              )}
              <div>
                <label className="field-label">Display Name *</label>
                <input className="field"
                  value={createForm.display_name}
                  onChange={e => setCreateForm({ ...createForm, display_name: e.target.value })} />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="field-label">External Ref</label>
                  <input className="field"
                    value={createForm.external_ref}
                    onChange={e => setCreateForm({ ...createForm, external_ref: e.target.value })} />
                </div>
                <div>
                  <label className="field-label">Date of Birth</label>
                  <input type="date" className="field"
                    value={createForm.date_of_birth}
                    onChange={e => setCreateForm({ ...createForm, date_of_birth: e.target.value })} />
                </div>
              </div>
              <div>
                <label className="field-label">Biological Sex</label>
                <select className="field"
                  value={createForm.biological_sex}
                  onChange={e => setCreateForm({ ...createForm, biological_sex: e.target.value })}>
                  <option value="">Prefer not to specify</option>
                  <option value="Female">Female</option>
                  <option value="Male">Male</option>
                  <option value="Other">Other</option>
                </select>
              </div>

              <div className="pt-4" style={{ borderTop: '1px solid var(--hair)' }}>
                <p className="section-title mb-3">Health & Demographic Profile (self-reported)</p>
                <p className="mb-3 text-[12px] leading-relaxed text-ink-3">
                  Captured once per patient and combined with per-session telemetry (SSQ, NASA-TLX, frame data)
                  for scientific analysis. Covered by the participant's consent (P-C4) and scrubbed on erasure.
                </p>
                <div className="grid grid-cols-3 gap-4 mb-4">
                  <div>
                    <label className="field-label">Age (years)</label>
                    <input type="number" min={0} max={130} className="field"
                      value={createForm.age_years}
                      onChange={e => setCreateForm({ ...createForm, age_years: e.target.value })} />
                  </div>
                  <div>
                    <label className="field-label">Height (cm)</label>
                    <input type="number" step="0.1" className="field"
                      value={createForm.height_cm}
                      onChange={e => setCreateForm({ ...createForm, height_cm: e.target.value })} />
                  </div>
                  <div>
                    <label className="field-label">Weight (kg)</label>
                    <input type="number" step="0.1" className="field"
                      value={createForm.weight_kg}
                      onChange={e => setCreateForm({ ...createForm, weight_kg: e.target.value })} />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4 mb-4">
                  <div>
                    <label className="field-label">Dominant Hand</label>
                    <select className="field"
                      value={createForm.dominant_hand}
                      onChange={e => setCreateForm({ ...createForm, dominant_hand: e.target.value })}>
                      <option value="">Unspecified</option>
                      <option value="Right">Right</option>
                      <option value="Left">Left</option>
                      <option value="Ambidextrous">Ambidextrous</option>
                    </select>
                  </div>
                  <div>
                    <label className="field-label">VR Experience Level</label>
                    <select className="field"
                      value={createForm.vr_experience_level}
                      onChange={e => setCreateForm({ ...createForm, vr_experience_level: e.target.value })}>
                      <option value="">Unspecified</option>
                      <option value="None">None</option>
                      <option value="Novice">Novice</option>
                      <option value="Intermediate">Intermediate</option>
                      <option value="Experienced">Experienced</option>
                      <option value="Expert">Expert</option>
                    </select>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4 mb-4">
                  <div>
                    <label className="field-label">Estimated VR Hours (lifetime)</label>
                    <input type="number" step="0.5" className="field"
                      value={createForm.vr_experience_hours_estimate}
                      onChange={e => setCreateForm({ ...createForm, vr_experience_hours_estimate: e.target.value })} />
                  </div>
                  <div>
                    <label className="field-label">Gaming Hours/Week</label>
                    <input type="number" step="0.5" className="field"
                      value={createForm.gaming_experience_hours_per_week}
                      onChange={e => setCreateForm({ ...createForm, gaming_experience_hours_per_week: e.target.value })} />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4 mb-4">
                  <div>
                    <label className="field-label">Vision Correction</label>
                    <select className="field"
                      value={createForm.vision_correction}
                      onChange={e => setCreateForm({ ...createForm, vision_correction: e.target.value })}>
                      <option value="">Unspecified</option>
                      <option value="None">None</option>
                      <option value="Glasses">Glasses</option>
                      <option value="Contact Lenses">Contact Lenses</option>
                      <option value="Corrective Surgery">Corrective Surgery (e.g. LASIK)</option>
                    </select>
                  </div>
                  <div>
                    <label className="field-label">Vision Impairment</label>
                    <input className="field"
                      placeholder="e.g. color blindness, low vision"
                      value={createForm.vision_impairment}
                      onChange={e => setCreateForm({ ...createForm, vision_impairment: e.target.value })} />
                  </div>
                </div>
                <div className="mb-4">
                  <label className="field-label">Motion Sickness Susceptibility</label>
                  <select className="field"
                    value={createForm.motion_sickness_susceptibility}
                    onChange={e => setCreateForm({ ...createForm, motion_sickness_susceptibility: e.target.value })}>
                    <option value="">Unspecified</option>
                    <option value="none">None</option>
                    <option value="mild">Mild</option>
                    <option value="moderate">Moderate</option>
                    <option value="severe">Severe</option>
                  </select>
                </div>
                <div>
                  <label className="field-label">Other Relevant Health Conditions</label>
                  <textarea className="field" rows={2}
                    placeholder="e.g. vestibular disorder, epilepsy, chronic dizziness"
                    value={createForm.relevant_health_conditions}
                    onChange={e => setCreateForm({ ...createForm, relevant_health_conditions: e.target.value })} />
                </div>
              </div>

              <div>
                <label className="field-label">Notes</label>
                <textarea className="field" rows={2}
                  value={createForm.notes}
                  onChange={e => setCreateForm({ ...createForm, notes: e.target.value })} />
              </div>

              <div className="flex items-start gap-3 pt-4" style={{ borderTop: '1px solid var(--hair)' }}>
                <ShieldCheck className="mt-0.5 h-4 w-4 flex-none" style={{ color: 'var(--s1)' }} />
                <div>
                  <span className="text-[13px] font-medium">Next: the participant gives consent themselves</span>
                  <p className="mt-1 text-[12px] leading-relaxed text-ink-3">
                    Hand the screen to the participant. They read the short notice and tick their own consent
                    boxes; you then confirm how consent was obtained. Nothing on this form is stored unless they
                    agree. The consent, its exact wording and your confirmation are recorded as evidence
                    (GDPR Art. 7(1), Art. 9(2)(a)).
                  </p>
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-2 px-5 py-4" style={{ borderTop: '1px solid var(--hair)' }}>
              <button onClick={() => setShowCreate(false)} className="btn-clay">Cancel</button>
              <button onClick={handleCreate} disabled={isSaving} className="btn-accent">
                {isSaving ? 'Saving...' : 'Continue to participant consent'}
              </button>
            </div>
          </div>
        </div>
      )}

      {consentFlow && (
        <ParticipantConsentFlow
          onSubmit={consentFlow.mode === 'create' ? submitNewPatient : submitReconsent(consentFlow.patient.patient_id)}
          onClose={closeConsentFlow}
        />
      )}

      {/* Withdrawal: the participant chooses what should happen (GDPR-10) */}
      {withdrawFor && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="withdraw-title">
          <div className="modal-card flex max-w-lg flex-col overflow-hidden p-0">
            <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: '1px solid var(--hair)' }}>
              <h2 id="withdraw-title" className="m-0 text-[16px] font-semibold">Withdraw your consent</h2>
              <button onClick={() => setWithdrawFor(null)} aria-label="Close withdrawal dialog" className="btn-ghost"><X className="h-[18px] w-[18px]" /></button>
            </div>
            <div className="space-y-3 overflow-y-auto px-5 py-5">
              <p className="m-0 text-[13px]">You can withdraw at any time, and you don't have to give a reason. Please choose what should happen:</p>
              {WITHDRAWAL_OPTIONS.map(option => (
                <label key={option.scope} className="flex cursor-pointer items-start gap-3 rounded-md p-3" style={{ background: 'var(--well-grid)' }}>
                  <input type="radio" name="withdrawal-scope" className="mt-1 h-4 w-4 flex-none" style={{ accentColor: 'var(--s1)' }}
                    checked={withdrawScope === option.scope} onChange={() => setWithdrawScope(option.scope)} />
                  <div>
                    <span className="text-[13px] font-semibold">{option.title}</span>
                    <p className="m-0 mt-1 text-[12px] leading-relaxed text-ink-3">{option.body}</p>
                  </div>
                </label>
              ))}
              {withdrawError && (
                <div className="notice tone-2 items-start text-[13px]">
                  <AlertCircle className="mt-0.5 h-4 w-4 flex-none text-tone" /><p className="m-0">{withdrawError}</p>
                </div>
              )}
            </div>
            <div className="flex justify-end gap-2 px-5 py-4" style={{ borderTop: '1px solid var(--hair)' }}>
              <button onClick={() => setWithdrawFor(null)} className="btn-clay">Go back</button>
              <button onClick={confirmWithdrawal} className="btn-accent">Confirm</button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {editing && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="edit-patient-title">
          <div className="modal-card flex max-w-lg flex-col overflow-hidden p-0">
            <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: '1px solid var(--hair)' }}>
              <h2 id="edit-patient-title" className="m-0 text-[16px] font-semibold">Edit Patient</h2>
              <button onClick={() => setEditing(null)} aria-label="Close edit patient form" className="btn-ghost"><X className="h-[18px] w-[18px]" /></button>
            </div>
            <div className="space-y-4 overflow-y-auto px-5 py-5">
              <div>
                <label className="field-label">Display Name</label>
                <input className="field"
                  value={editForm.display_name || ''} onChange={e => setEditForm({ ...editForm, display_name: e.target.value })} />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="field-label">External Ref</label>
                  <input className="field"
                    value={editForm.external_ref || ''} onChange={e => setEditForm({ ...editForm, external_ref: e.target.value })} />
                </div>
                <div>
                  <label className="field-label">Date of Birth</label>
                  <input type="date" className="field"
                    value={editForm.date_of_birth || ''} onChange={e => setEditForm({ ...editForm, date_of_birth: e.target.value })} />
                </div>
              </div>
              <div>
                <label className="field-label">Biological Sex</label>
                <select className="field"
                  value={editForm.biological_sex || ''}
                  onChange={e => setEditForm({ ...editForm, biological_sex: e.target.value })}>
                  <option value="">Prefer not to specify</option>
                  <option value="Female">Female</option>
                  <option value="Male">Male</option>
                  <option value="Other">Other</option>
                </select>
              </div>

              <div className="pt-4" style={{ borderTop: '1px solid var(--hair)' }}>
                <p className="section-title mb-3">Health & Demographic Profile (self-reported)</p>
                <div className="grid grid-cols-3 gap-4 mb-4">
                  <div>
                    <label className="field-label">Age (years)</label>
                    <input type="number" min={0} max={130} className="field"
                      value={editForm.age_years ?? ''}
                      onChange={e => setEditForm({ ...editForm, age_years: e.target.value })} />
                  </div>
                  <div>
                    <label className="field-label">Height (cm)</label>
                    <input type="number" step="0.1" className="field"
                      value={editForm.height_cm ?? ''}
                      onChange={e => setEditForm({ ...editForm, height_cm: e.target.value })} />
                  </div>
                  <div>
                    <label className="field-label">Weight (kg)</label>
                    <input type="number" step="0.1" className="field"
                      value={editForm.weight_kg ?? ''}
                      onChange={e => setEditForm({ ...editForm, weight_kg: e.target.value })} />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4 mb-4">
                  <div>
                    <label className="field-label">Dominant Hand</label>
                    <select className="field"
                      value={editForm.dominant_hand || ''}
                      onChange={e => setEditForm({ ...editForm, dominant_hand: e.target.value })}>
                      <option value="">Unspecified</option>
                      <option value="Right">Right</option>
                      <option value="Left">Left</option>
                      <option value="Ambidextrous">Ambidextrous</option>
                    </select>
                  </div>
                  <div>
                    <label className="field-label">VR Experience Level</label>
                    <select className="field"
                      value={editForm.vr_experience_level || ''}
                      onChange={e => setEditForm({ ...editForm, vr_experience_level: e.target.value })}>
                      <option value="">Unspecified</option>
                      <option value="None">None</option>
                      <option value="Novice">Novice</option>
                      <option value="Intermediate">Intermediate</option>
                      <option value="Experienced">Experienced</option>
                      <option value="Expert">Expert</option>
                    </select>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4 mb-4">
                  <div>
                    <label className="field-label">Estimated VR Hours (lifetime)</label>
                    <input type="number" step="0.5" className="field"
                      value={editForm.vr_experience_hours_estimate ?? ''}
                      onChange={e => setEditForm({ ...editForm, vr_experience_hours_estimate: e.target.value })} />
                  </div>
                  <div>
                    <label className="field-label">Gaming Hours/Week</label>
                    <input type="number" step="0.5" className="field"
                      value={editForm.gaming_experience_hours_per_week ?? ''}
                      onChange={e => setEditForm({ ...editForm, gaming_experience_hours_per_week: e.target.value })} />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4 mb-4">
                  <div>
                    <label className="field-label">Vision Correction</label>
                    <select className="field"
                      value={editForm.vision_correction || ''}
                      onChange={e => setEditForm({ ...editForm, vision_correction: e.target.value })}>
                      <option value="">Unspecified</option>
                      <option value="None">None</option>
                      <option value="Glasses">Glasses</option>
                      <option value="Contact Lenses">Contact Lenses</option>
                      <option value="Corrective Surgery">Corrective Surgery (e.g. LASIK)</option>
                    </select>
                  </div>
                  <div>
                    <label className="field-label">Vision Impairment</label>
                    <input className="field"
                      placeholder="e.g. color blindness, low vision"
                      value={editForm.vision_impairment || ''}
                      onChange={e => setEditForm({ ...editForm, vision_impairment: e.target.value })} />
                  </div>
                </div>
                <div className="mb-4">
                  <label className="field-label">Motion Sickness Susceptibility</label>
                  <select className="field"
                    value={editForm.motion_sickness_susceptibility || ''}
                    onChange={e => setEditForm({ ...editForm, motion_sickness_susceptibility: e.target.value })}>
                    <option value="">Unspecified</option>
                    <option value="none">None</option>
                    <option value="mild">Mild</option>
                    <option value="moderate">Moderate</option>
                    <option value="severe">Severe</option>
                  </select>
                </div>
                <div>
                  <label className="field-label">Other Relevant Health Conditions</label>
                  <textarea className="field" rows={2}
                    placeholder="e.g. vestibular disorder, epilepsy, chronic dizziness"
                    value={editForm.relevant_health_conditions || ''}
                    onChange={e => setEditForm({ ...editForm, relevant_health_conditions: e.target.value })} />
                </div>
              </div>

              <div>
                <label className="field-label">Notes</label>
                <textarea className="field" rows={2}
                  value={editForm.notes || ''} onChange={e => setEditForm({ ...editForm, notes: e.target.value })} />
              </div>
            </div>
            <div className="flex justify-end gap-2 px-5 py-4" style={{ borderTop: '1px solid var(--hair)' }}>
              <button onClick={() => setEditing(null)} className="btn-clay">Cancel</button>
              <button onClick={handleSaveEdit} className="btn-accent">
                <Save className="w-4 h-4" /> Save
              </button>
            </div>
          </div>
        </div>
      )}
      {sessionsFor && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="patient-sessions-title">
            <div className="modal-card flex max-w-2xl flex-col overflow-hidden p-0">
            <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: '1px solid var(--hair)' }}>
                <div>
                <h2 id="patient-sessions-title" className="m-0 text-[16px] font-semibold">Sessions for {sessionsFor.patient.display_name}</h2>
                <p className="mt-0.5 text-[11px] text-ink-3">{sessionsFor.sessions.length} recorded session(s)</p>
                </div>
                <button onClick={() => setSessionsFor(null)} aria-label="Close patient sessions" className="btn-ghost"><X className="h-[18px] w-[18px]" /></button>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
                {sessionsFor.sessions.length === 0 ? (
                <p className="py-8 text-center text-[13px] text-ink-3">No sessions recorded yet for this patient.</p>
                ) : (
                <table className="data-table">
                    <thead>
                    <tr>
                        <th>Session</th>
                        <th>Date</th>
                        <th>HMD</th>
                        <th>Dropped Frames</th>
                    </tr>
                    </thead>
                    <tbody>
                    {sessionsFor.sessions.map((s: any) => (
                        <tr key={s.session_id}>
                        <td className="num">{s.session_id.split('-')[0]}…</td>
                        <td className="num">{s.start_timestamp_utc}</td>
                        <td>{s.hmd_model}</td>
                        <td className="num">{s.total_dropped_frames}</td>
                        </tr>
                    ))}
                    </tbody>
                </table>
                )}
            </div>
            </div>
        </div>
        )}
    </div>
  );
};
