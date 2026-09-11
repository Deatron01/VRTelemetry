import React, { useEffect, useState } from 'react';
import { PlayCircle, ShieldAlert, ShieldCheck, Cpu, Network, StopCircle, Server, Users } from 'lucide-react';
import { PostSessionQuestionnaire } from '../components/PostSessionQuestionnaire';

interface Patient {
  patient_id: string;
  display_name: string;
  gdpr_consent_given: number;
  is_anonymized: number;
}

const API = 'http://localhost:8000';

interface HubCheck {
  checking?: boolean;
  reachable?: boolean;
  detail?: string;
  service?: string;
  version?: string;
  healthy?: boolean;
}

const BACKENDS = [
  { value: 'auto', label: 'Auto-Detect' },
  { value: 'openxr', label: 'OpenXR' },
  { value: 'oculus', label: 'Oculus' },
  { value: 'steamvr', label: 'SteamVR' },
  { value: 'quest_udp', label: 'Quest UDP' },
];

export const NewSession = () => {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [isRecording, setIsRecording] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [completedSessionId, setCompletedSessionId] = useState<string | null>(null);

  const [form, setForm] = useState({
    patient_id: '',
    subject_id: '',
    backend: 'auto',
    port: 5005,
  });

  // The hub address is a property of this machine, not of this session.
  //
  // It used to live in `form` above, with 'http://192.168.1.X:9000' as its
  // literal value — a placeholder with a letter where an octet belongs, sent
  // with every start request. VRT-6 removed that string from the backend and
  // made the settings validator reject it; the form went on overriding whatever
  // was configured with it, so on a two-machine setup every recording uploaded
  // to an address that cannot exist. Now it is loaded from, and saved to, the
  // workstation's own configuration.
  const [hubUrl, setHubUrl] = useState('');
  const [hubCheck, setHubCheck] = useState<HubCheck | null>(null);

  useEffect(() => {
    fetch(`${API}/api/patients`)
      .then(r => r.json())
      .then((data: Patient[]) => setPatients(data.filter(p => !p.is_anonymized)))
      .catch(() => setPatients([]));

    fetch(`${API}/api/config/central-server`)
      .then(r => r.json())
      .then(d => setHubUrl(d.central_server_url || ''))
      .catch(() => setHubUrl(''));
  }, []);

  const saveHubUrl = async (value: string) => {
    setHubCheck(null);
    try {
      await fetch(`${API}/api/config/central-server`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ central_server_url: value })
      });
    } catch {
      // Saving to our own loopback backend. If that is unreachable nothing on
      // this page works, and the failure is already visible everywhere else.
    }
  };

  // Asks the workstation to ask the hub. Deliberately does not save: an address
  // that fails the check is still worth keeping — the hub may just be off.
  const testHubUrl = async () => {
    setHubCheck({ checking: true });
    try {
      const response = await fetch(`${API}/api/config/central-server/check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ central_server_url: hubUrl || null })
      });
      setHubCheck(await response.json());
    } catch (err) {
      setHubCheck({ reachable: false, detail: err instanceof Error ? err.message : 'Check failed.' });
    }
  };

  const selectedPatient = patients.find(p => p.patient_id === form.patient_id);

  const handleStart = async () => {
    if (!form.patient_id) {
      setError("Select a patient before starting acquisition.");
      return;
    }
    if (selectedPatient && !selectedPatient.gdpr_consent_given) {
      setError("This patient's GDPR consent is not active. Record a new consent from the Patients page first.");
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch(`${API}/api/recording/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form)
      });

      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Failed to start engine.');

      setIsRecording(true);
      setCompletedSessionId(data.session_id || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleStop = async () => {
    setIsLoading(true);
    try {
      await fetch(`${API}/api/recording/stop`, { method: 'POST' });
      setIsRecording(false);
      // completedSessionId (captured from /api/recording/start's response) is already
      // set — surfacing the post-session questionnaire modal right now, while the
      // experience is still fresh, is the whole point of collecting SSQ/NASA-TLX at all.
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to stop recording.');
    } finally {
      setIsLoading(false);
    }
  };

  const status: [string, React.ReactNode][] = isRecording
    ? [
        ['Engine state', <span key="s" className="chip tone-2 mono animate-pulse">RECORDING</span>],
        ['Subject binding', <span key="b" className="mono text-[12px]" style={{ color: 'var(--s1)' }}>{selectedPatient?.display_name || form.subject_id || '—'}</span>],
        ['Active pipeline', <span key="p" className="mono text-[12px]">{form.backend.toUpperCase()}</span>],
        ['Sync target', <span key="t" className="mono block max-w-[180px] truncate text-[12px]">{hubUrl || 'not configured'}</span>],
      ]
    : [
        ['Engine state', <span key="s" className="chip mono" style={{ color: 'var(--ink-3)', background: 'var(--well-grid)' }}>IDLE</span>],
        ['Target output', <span key="o" className="mono text-[12px]">/Sessions/</span>],
        ['Active pipeline', <span key="p" className="mono text-[12px]">{form.backend.toUpperCase()}</span>],
        ['Sync target', <span key="t" className="mono block max-w-[180px] truncate text-[12px]">{hubUrl || 'not configured'}</span>],
      ];

  return (
    <div className="mx-auto flex max-w-[1180px] flex-col gap-4">
      <div>
        <h1 className="page-title">Live Acquisition Control</h1>
        <p className="page-sub">Configure runtime backend and initialize real-time data harvesting.</p>
      </div>

      <div className="grid grid-cols-1 items-start gap-3.5 lg:grid-cols-[1.15fr_1fr]">

        {/* --- Configuration ------------------------------------------------ */}
        <div className="clay relative flex flex-col gap-4 overflow-hidden p-4">
          {isRecording && (
            <div className="glass-bare absolute inset-0 z-10 flex flex-col items-center justify-center gap-2">
              <span
                className="h-3.5 w-3.5 animate-pulse rounded-full"
                style={{ background: 'var(--s2)', boxShadow: '0 0 0 6px var(--s2-soft)' }}
                aria-hidden="true"
              />
              <h3 className="m-0 mt-2 text-[14px] font-semibold">Acquisition Active</h3>
              <p className="m-0 text-[12px] text-ink-3">Hardware telemetry is being recorded to Parquet.</p>
            </div>
          )}

          <div className="section-head mb-0">
            <span style={{ color: 'var(--s1)' }}><Cpu className="h-4 w-4" /></span>
            <h2 className="section-title">Session Parameters</h2>
            <div className="section-rule" />
          </div>

          <div>
            <label htmlFor="acq-patient" className="field-label flex items-center gap-1.5">
              <Users className="h-3 w-3" /> Patient
            </label>
            <select
              id="acq-patient"
              value={form.patient_id}
              onChange={e => setForm({ ...form, patient_id: e.target.value })}
              className="field"
            >
              <option value="">Select a patient…</option>
              {patients.map(p => (
                <option key={p.patient_id} value={p.patient_id} disabled={!p.gdpr_consent_given}>
                  {p.display_name}{!p.gdpr_consent_given ? ' (consent withdrawn)' : ''}
                </option>
              ))}
            </select>
            {patients.length === 0 && (
              <p className="mt-1.5 text-[11px]" style={{ color: 'var(--s4)' }}>
                No patients yet — create one on the Patients page first.
              </p>
            )}
            {selectedPatient?.gdpr_consent_given === 1 && (
              <p className="mt-1.5 flex items-center gap-1.5 text-[11px]" style={{ color: 'var(--s6)' }}>
                <ShieldCheck className="h-3.5 w-3.5" /> Consent active for this subject
              </p>
            )}
          </div>

          <div>
            <span className="field-label flex items-center gap-1.5"><Cpu className="h-3 w-3" /> Runtime Backend</span>
            <div className="seg flex-wrap" role="group" aria-label="Runtime backend">
              {BACKENDS.map(b => (
                <button
                  key={b.value}
                  onClick={() => setForm({ ...form, backend: b.value })}
                  aria-pressed={form.backend === b.value}
                  className={form.backend === b.value ? 'seg-item is-active' : 'seg-item'}
                >
                  {b.label}
                </button>
              ))}
            </div>
          </div>

          {form.backend === 'quest_udp' && (
            <div>
              <label htmlFor="acq-port" className="field-label flex items-center gap-1.5">
                <Network className="h-3 w-3" /> Binding Port (UDP)
              </label>
              <input
                id="acq-port"
                type="number"
                value={form.port}
                onChange={e => setForm({ ...form, port: Number(e.target.value) })}
                className="field field-mono"
              />
            </div>
          )}

          <div>
            <label htmlFor="acq-server" className="field-label flex items-center gap-1.5">
              <Server className="h-3 w-3" /> Central Server Address
            </label>
            <div className="flex gap-2">
              <input
                id="acq-server"
                type="text"
                value={hubUrl}
                onChange={e => { setHubUrl(e.target.value); setHubCheck(null); }}
                onBlur={e => saveHubUrl(e.target.value.trim())}
                placeholder="https://192.168.1.50:9000"
                className="field field-mono flex-1"
              />
              <button
                type="button"
                onClick={testHubUrl}
                disabled={hubCheck?.checking}
                className="btn-clay flex-none whitespace-nowrap"
              >
                {hubCheck?.checking ? 'Testing…' : 'Test'}
              </button>
            </div>
            <p className="mt-1.5 text-[11px] text-ink-3">
              Saved for this machine, not just this session. Where completed sessions are synced
              after recording stops. Leave empty to work offline — sessions queue locally and
              upload when a hub is configured and reachable.
            </p>
            {hubCheck && !hubCheck.checking && (
              <p
                className="mt-1.5 text-[11px] mono"
                style={{ color: hubCheck.reachable ? 'var(--s1)' : 'var(--s2)' }}
              >
                {hubCheck.reachable
                  ? `Reachable — ${hubCheck.service} ${hubCheck.version}${hubCheck.healthy ? '' : ' (database not answering)'}`
                  : hubCheck.detail}
              </p>
            )}
          </div>

          <div className="mt-auto flex items-start gap-3 pt-4" style={{ borderTop: '1px solid var(--hair)' }}>
            <ShieldCheck className="mt-0.5 h-4 w-4 flex-none" style={{ color: 'var(--s1)' }} />
            <div>
              <span className="text-[13px] font-medium">Authorised by the participant's recorded consent</span>
              <p className="mt-1 text-[12px] leading-relaxed text-ink-3">
                Recording starts only if the selected participant has an active consent for the configured study,
                given on the consent screen. The session is stamped with that consent's id. If there is none, the
                server says so and nothing is recorded.
              </p>
            </div>
          </div>
        </div>

        {/* --- Status + action --------------------------------------------- */}
        <div className="flex flex-col gap-3.5">
          <div className="clay flex flex-col gap-4 p-4">
            <div className="section-head mb-0">
              <span style={{ color: 'var(--s6)' }}><ShieldAlert className="h-4 w-4" /></span>
              <h2 className="section-title">Operational Status</h2>
              <div className="section-rule" />
            </div>

            {error && (
              <div className="notice tone-2 items-start text-[13px]">
                <ShieldAlert className="mt-0.5 h-4 w-4 flex-none text-tone" />
                <p className="m-0 flex-1 text-ink-2">{error}</p>
              </div>
            )}

            <div className="well flex flex-col gap-2.5 p-3">
              {status.map(([label, value]) => (
                <div key={label} className="flex items-center justify-between gap-3 text-[12px]">
                  <span className="text-ink-3">{label}</span>
                  {value}
                </div>
              ))}
            </div>

            {!isRecording ? (
              <button
                onClick={handleStart}
                disabled={isLoading || !selectedPatient?.gdpr_consent_given}
                className="btn-accent btn-accent-lg w-full justify-center"
              >
                <PlayCircle className="h-[18px] w-[18px]" />
                {isLoading ? 'Initializing hardware…' : 'Initialize Telemetry Engine'}
              </button>
            ) : (
              <button
                onClick={handleStop}
                disabled={isLoading}
                className="btn-accent btn-accent-lg w-full justify-center"
                style={{ background: 'linear-gradient(145deg, var(--s2), var(--s2))' }}
              >
                <StopCircle className="h-[18px] w-[18px]" />
                {isLoading ? 'Sealing Parquet buffers…' : 'Terminate Recording'}
              </button>
            )}
          </div>

          <div className="clay p-4">
            <div className="stat-label mb-3">Hardware handshake</div>
            <div className="well flex flex-col gap-2.5 p-3">
              {[
                { label: 'HMD pose stream', ready: true },
                { label: 'Binocular eye tracker', ready: true },
                { label: 'Cardiovascular sensor', ready: true },
                { label: 'Controller pair', ready: true },
              ].map(row => (
                <div key={row.label} className="flex items-center gap-2.5 text-[12px]">
                  <span
                    className="h-[6px] w-[6px] flex-none rounded-full"
                    style={{ background: isRecording ? 'var(--s6)' : 'var(--ink-3)' }}
                    aria-hidden="true"
                  />
                  <span className="flex-1 text-ink-2">{row.label}</span>
                  <span className="mono text-[11px] text-ink-3">{isRecording ? 'streaming' : 'idle'}</span>
                </div>
              ))}
            </div>
            <p className="m-0 mt-2.5 text-[11px] text-ink-3">
              Channel state reflects the engine, not a per-device probe — a channel shows as streaming once acquisition
              is running.
            </p>
          </div>
        </div>
      </div>

      {completedSessionId && !isRecording && (
        <PostSessionQuestionnaire
          sessionId={completedSessionId}
          onClose={() => setCompletedSessionId(null)}
          onSaved={() => setCompletedSessionId(null)}
        />
      )}
    </div>
  );
};
