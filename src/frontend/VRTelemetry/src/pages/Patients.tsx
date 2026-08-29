import React, { useEffect, useState } from 'react';
import { Users, Plus, Edit2, Save, Trash2, ShieldAlert, ShieldOff, X, AlertCircle, Database } from 'lucide-react';

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
}

const emptyForm = {
  display_name: '',
  external_ref: '',
  date_of_birth: '',
  biological_sex: '',
  notes: '',
  gdpr_consent_given: false,
};

export const Patients = () => {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState(emptyForm);
  const [createError, setCreateError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  const [editing, setEditing] = useState<Patient | null>(null);
  const [editForm, setEditForm] = useState<Partial<Patient>>({});

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
    if (!createForm.gdpr_consent_given) {
      setCreateError('Explicit GDPR consent is required to create a patient record.');
      return;
    }
    setIsSaving(true);
    try {
      const res = await fetch('http://localhost:8000/api/patients', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(createForm),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to create patient.');
      setShowCreate(false);
      setCreateForm(emptyForm);
      fetchPatients();
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : 'Network error.');
    } finally {
      setIsSaving(false);
    }
  };

  const openEdit = (p: Patient) => {
    setEditing(p);
    setEditForm({
      display_name: p.display_name,
      external_ref: p.external_ref,
      date_of_birth: p.date_of_birth,
      biological_sex: p.biological_sex,
      notes: p.notes,
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
        body: JSON.stringify(editForm),
      });
      if (!res.ok) throw new Error('Failed to save changes.');
      setEditing(null);
      fetchPatients();
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Failed to save.');
    }
  };

  const handleWithdrawConsent = async (patientId: string) => {
    if (!confirm('Withdraw GDPR consent for this patient? New sessions cannot be started for them until a fresh consented record exists. Existing recordings are unaffected.')) return;
    await fetch(`http://localhost:8000/api/patients/${patientId}/withdraw-consent`, { method: 'POST' });
    fetchPatients();
  };

  const handleErase = async (patientId: string) => {
    if (!confirm('Erase this patient record (GDPR right to erasure)? Identifying fields will be permanently scrubbed. This cannot be undone.')) return;
    await fetch(`http://localhost:8000/api/patients/${patientId}`, { method: 'DELETE' });
    fetchPatients();
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6 flex flex-col h-[calc(100vh-140px)]">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Users className="w-8 h-8 text-research-graphite" />
          <div>
            <h1 className="text-2xl font-semibold text-research-graphite">Patient Registry</h1>
            <p className="text-sm text-research-muted">Durable subject identities used across recording sessions. GDPR consent is required and logged for every record.</p>
          </div>
        </div>
        <button className="glass-button bg-research-blue/10 text-research-blue border-research-blue/20" onClick={() => setShowCreate(true)}>
          <Plus className="w-4 h-4" /> New Patient
        </button>
      </div>

      <div className="glass-panel overflow-hidden flex flex-col flex-1">
        {isLoading ? (
          <div className="flex-1 flex items-center justify-center text-research-muted">Loading...</div>
        ) : error ? (
          <div className="flex-1 flex flex-col items-center justify-center text-red-500 gap-2">
            <AlertCircle className="w-8 h-8" /><p className="font-medium">{error}</p>
          </div>
        ) : patients.length === 0 ? (
          <div className="flex-1 flex items-center justify-center text-research-muted text-sm">
            No patients yet. Create one to enable recording.
          </div>
        ) : (
          <div className="overflow-auto flex-1 p-0">
            <table className="w-full text-sm text-left">
              <thead className="text-xs text-research-muted uppercase bg-slate-50/50 sticky top-0 backdrop-blur-md border-b border-research-border">
                <tr>
                  <th className="px-6 py-4 font-medium tracking-wider">Name</th>
                  <th className="px-6 py-4 font-medium tracking-wider">External Ref</th>
                  <th className="px-6 py-4 font-medium tracking-wider">DOB</th>
                  <th className="px-6 py-4 font-medium tracking-wider">GDPR Consent</th>
                  <th className="px-6 py-4 font-medium tracking-wider text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-research-border">
                {patients.map(p => (
                  <tr key={p.patient_id} className="hover:bg-slate-50/50 transition-colors">
                    <td className="px-6 py-4 font-medium">{p.display_name}</td>
                    <td className="px-6 py-4 text-research-muted font-mono text-xs">{p.external_ref || '—'}</td>
                    <td className="px-6 py-4 text-research-muted">{p.date_of_birth || '—'}</td>
                    <td className="px-6 py-4">
                      {p.gdpr_consent_given ? (
                        <span className="inline-flex items-center gap-1 text-xs font-medium text-research-green bg-green-50 border border-green-200 px-2 py-1 rounded">
                          <ShieldAlert className="w-3.5 h-3.5" /> Active (v{p.gdpr_consent_version})
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-xs font-medium text-red-500 bg-red-50 border border-red-200 px-2 py-1 rounded">
                          <ShieldOff className="w-3.5 h-3.5" /> {p.is_anonymized ? 'Erased' : 'Withdrawn'}
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex justify-end gap-2">
                        {!p.is_anonymized && (
                          <>
                            <button onClick={() => handleViewSessions(p.patient_id)} className="p-1.5 hover:bg-slate-100 rounded" title="View recorded sessions">
                                <Database className="w-4 h-4 text-research-graphite" />
                            </button>
                            <button onClick={() => openEdit(p)} className="p-1.5 hover:bg-slate-100 rounded" title="Edit">
                              <Edit2 className="w-4 h-4 text-research-blue" />
                            </button>
                            {p.gdpr_consent_given === 1 && (
                              <button onClick={() => handleWithdrawConsent(p.patient_id)} className="p-1.5 hover:bg-slate-100 rounded" title="Withdraw consent">
                                <ShieldOff className="w-4 h-4 text-amber-500" />
                              </button>
                            )}
                            <button onClick={() => handleErase(p.patient_id)} className="p-1.5 hover:bg-slate-100 rounded" title="Erase (GDPR right to erasure)">
                              <Trash2 className="w-4 h-4 text-red-500" />
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

      {/* Create Modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-slate-900/20 backdrop-blur-sm">
          <div className="bg-white/95 backdrop-blur-xl border border-research-border shadow-2xl rounded-2xl w-full max-w-lg overflow-hidden">
            <div className="px-6 py-4 border-b border-research-border flex justify-between items-center">
              <h2 className="text-lg font-semibold text-research-graphite">New Patient</h2>
              <button onClick={() => setShowCreate(false)} className="p-1 hover:bg-slate-100 rounded-full">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              {createError && (
                <div className="p-3 bg-red-50 border border-red-100 rounded-lg text-sm text-red-600 flex items-start gap-2">
                  <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" /><p>{createError}</p>
                </div>
              )}
              <div>
                <label className="block text-xs font-semibold text-research-muted uppercase tracking-wider mb-1">Display Name *</label>
                <input className="w-full text-sm border border-research-border rounded-lg px-3 py-2 bg-white"
                  value={createForm.display_name}
                  onChange={e => setCreateForm({ ...createForm, display_name: e.target.value })} />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-research-muted uppercase tracking-wider mb-1">External Ref</label>
                  <input className="w-full text-sm border border-research-border rounded-lg px-3 py-2 bg-white"
                    value={createForm.external_ref}
                    onChange={e => setCreateForm({ ...createForm, external_ref: e.target.value })} />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-research-muted uppercase tracking-wider mb-1">Date of Birth</label>
                  <input type="date" className="w-full text-sm border border-research-border rounded-lg px-3 py-2 bg-white"
                    value={createForm.date_of_birth}
                    onChange={e => setCreateForm({ ...createForm, date_of_birth: e.target.value })} />
                </div>
              </div>
              <div>
                <label className="block text-xs font-semibold text-research-muted uppercase tracking-wider mb-1">Biological Sex</label>
                <select className="w-full text-sm border border-research-border rounded-lg px-3 py-2 bg-white"
                  value={createForm.biological_sex}
                  onChange={e => setCreateForm({ ...createForm, biological_sex: e.target.value })}>
                  <option value="">Prefer not to specify</option>
                  <option value="Female">Female</option>
                  <option value="Male">Male</option>
                  <option value="Other">Other</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-semibold text-research-muted uppercase tracking-wider mb-1">Notes</label>
                <textarea className="w-full text-sm border border-research-border rounded-lg px-3 py-2 bg-white" rows={2}
                  value={createForm.notes}
                  onChange={e => setCreateForm({ ...createForm, notes: e.target.value })} />
              </div>

              <label className="flex items-start gap-3 cursor-pointer group border-t border-research-border pt-4">
                <input type="checkbox" className="mt-0.5 w-4 h-4 rounded border-research-border text-research-blue"
                  checked={createForm.gdpr_consent_given}
                  onChange={e => setCreateForm({ ...createForm, gdpr_consent_given: e.target.checked })} />
                <div>
                  <span className="text-sm font-medium text-research-graphite">Explicit GDPR Consent Confirmed *</span>
                  <p className="text-xs text-research-muted mt-1 leading-relaxed">
                    The subject has been informed of, and has explicitly consented to, the collection and
                    processing of their biometric telemetry and identifying record. Consent is logged with
                    a version and timestamp, and can be withdrawn at any time from this screen.
                  </p>
                </div>
              </label>
            </div>
            <div className="px-6 py-4 border-t border-research-border flex justify-end gap-2">
              <button onClick={() => setShowCreate(false)} className="glass-button bg-slate-50 text-research-graphite border-slate-200">Cancel</button>
              <button onClick={handleCreate} disabled={isSaving} className="glass-button bg-research-blue/10 text-research-blue border-research-blue/20 disabled:opacity-50">
                {isSaving ? 'Saving...' : 'Create Patient'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-slate-900/20 backdrop-blur-sm">
          <div className="bg-white/95 backdrop-blur-xl border border-research-border shadow-2xl rounded-2xl w-full max-w-lg overflow-hidden">
            <div className="px-6 py-4 border-b border-research-border flex justify-between items-center">
              <h2 className="text-lg font-semibold text-research-graphite">Edit Patient</h2>
              <button onClick={() => setEditing(null)} className="p-1 hover:bg-slate-100 rounded-full"><X className="w-5 h-5" /></button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-xs font-semibold text-research-muted uppercase tracking-wider mb-1">Display Name</label>
                <input className="w-full text-sm border border-research-border rounded-lg px-3 py-2 bg-white"
                  value={editForm.display_name || ''} onChange={e => setEditForm({ ...editForm, display_name: e.target.value })} />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-research-muted uppercase tracking-wider mb-1">External Ref</label>
                  <input className="w-full text-sm border border-research-border rounded-lg px-3 py-2 bg-white"
                    value={editForm.external_ref || ''} onChange={e => setEditForm({ ...editForm, external_ref: e.target.value })} />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-research-muted uppercase tracking-wider mb-1">Date of Birth</label>
                  <input type="date" className="w-full text-sm border border-research-border rounded-lg px-3 py-2 bg-white"
                    value={editForm.date_of_birth || ''} onChange={e => setEditForm({ ...editForm, date_of_birth: e.target.value })} />
                </div>
              </div>
              <div>
                <label className="block text-xs font-semibold text-research-muted uppercase tracking-wider mb-1">Notes</label>
                <textarea className="w-full text-sm border border-research-border rounded-lg px-3 py-2 bg-white" rows={2}
                  value={editForm.notes || ''} onChange={e => setEditForm({ ...editForm, notes: e.target.value })} />
              </div>
            </div>
            <div className="px-6 py-4 border-t border-research-border flex justify-end gap-2">
              <button onClick={() => setEditing(null)} className="glass-button bg-slate-50 text-research-graphite border-slate-200">Cancel</button>
              <button onClick={handleSaveEdit} className="glass-button bg-green-50 text-research-green border-green-200">
                <Save className="w-4 h-4" /> Save
              </button>
            </div>
          </div>
        </div>
      )}
      {sessionsFor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-slate-900/20 backdrop-blur-sm">
            <div className="bg-white/95 backdrop-blur-xl border border-research-border shadow-2xl rounded-2xl w-full max-w-2xl overflow-hidden max-h-[80vh] flex flex-col">
            <div className="px-6 py-4 border-b border-research-border flex justify-between items-center">
                <div>
                <h2 className="text-lg font-semibold text-research-graphite">Sessions for {sessionsFor.patient.display_name}</h2>
                <p className="text-xs text-research-muted mt-0.5">{sessionsFor.sessions.length} recorded session(s)</p>
                </div>
                <button onClick={() => setSessionsFor(null)} className="p-1 hover:bg-slate-100 rounded-full"><X className="w-5 h-5" /></button>
            </div>
            <div className="overflow-y-auto flex-1 p-4">
                {sessionsFor.sessions.length === 0 ? (
                <p className="text-sm text-research-muted text-center py-8">No sessions recorded yet for this patient.</p>
                ) : (
                <table className="w-full text-sm text-left">
                    <thead className="text-xs text-research-muted uppercase border-b border-research-border">
                    <tr>
                        <th className="py-2 pr-4">Session</th>
                        <th className="py-2 pr-4">Date</th>
                        <th className="py-2 pr-4">HMD</th>
                        <th className="py-2">Dropped Frames</th>
                    </tr>
                    </thead>
                    <tbody className="divide-y divide-research-border">
                    {sessionsFor.sessions.map((s: any) => (
                        <tr key={s.session_id}>
                        <td className="py-2 pr-4 font-mono text-xs">{s.session_id.split('-')[0]}...</td>
                        <td className="py-2 pr-4">{s.start_timestamp_utc}</td>
                        <td className="py-2 pr-4 text-research-muted">{s.hmd_model}</td>
                        <td className="py-2">{s.total_dropped_frames}</td>
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