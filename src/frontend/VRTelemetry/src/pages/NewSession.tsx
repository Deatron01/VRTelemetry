import React, { useEffect, useState } from 'react';
import { PlayCircle, ShieldAlert, Cpu, Network, User, StopCircle, Server, Users } from 'lucide-react';

interface Patient {
  patient_id: string;
  display_name: string;
  gdpr_consent_given: number;
  is_anonymized: number;
}
export const NewSession = () => {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [isRecording, setIsRecording] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [form, setForm] = useState({
    patient_id: '',
    subject_id: '',
    backend: 'auto',
    port: 5005,
    gdpr_consent: false,
    central_server_url: 'http://192.168.1.X:9000'
  });

  useEffect(() => {
    fetch('http://localhost:8000/api/patients')
      .then(r => r.json())
      .then((data: Patient[]) => setPatients(data.filter(p => !p.is_anonymized)))
      .catch(() => setPatients([]));
  }, []);

  const selectedPatient = patients.find(p => p.patient_id === form.patient_id);

  const handleStart = async () => {
    if (!form.patient_id) {
      setError("Select a patient before starting acquisition.");
      return;
    }
    if (selectedPatient && !selectedPatient.gdpr_consent_given) {
      setError("This patient's GDPR consent is not active. Re-consent them from the Patients page first.");
      return;
    }
    if (!form.gdpr_consent) {
      setError("Explicit GDPR consent confirmation is required to begin biometric acquisition.");
      return;
    }
    
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch('http://localhost:8000/api/recording/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form)
      });
      
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Failed to start engine.');
      
      setIsRecording(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleStop = async () => {
    setIsLoading(true);
    try {
      await fetch('http://localhost:8000/api/recording/stop', { method: 'POST' });
      setIsRecording(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to stop recording.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6 flex flex-col h-full">
      <div className="flex items-center gap-3 mb-4">
        <PlayCircle className="w-8 h-8 text-research-graphite" />
        <div>
          <h1 className="text-2xl font-semibold text-research-graphite">Live Acquisition Control</h1>
          <p className="text-sm text-research-muted">Configure runtime backend and initialize real-time data harvesting.</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-6 flex-1">
        {/* Configuration Panel */}
        <div className="glass-panel p-6 flex flex-col space-y-6 relative overflow-hidden">
          {isRecording && (
            <div className="absolute inset-0 bg-white/50 backdrop-blur-sm z-10 flex flex-col items-center justify-center">
              <div className="w-4 h-4 bg-red-500 rounded-full animate-pulse mb-3 shadow-[0_0_15px_rgba(239,68,68,0.7)]" />
              <h3 className="font-semibold text-research-graphite">Acquisition Active</h3>
              <p className="text-sm text-research-muted mt-1">Hardware telemetry is being recorded to Parquet.</p>
            </div>
          )}

          <h3 className="font-semibold text-research-graphite border-b border-research-border pb-2 flex items-center gap-2">
            <Cpu className="w-4 h-4 text-research-blue" /> Session Parameters
          </h3>

          <div className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-research-muted uppercase tracking-wider mb-1 flex items-center gap-1">
                <Users className="w-3 h-3" /> Patient
              </label>
              <select
                value={form.patient_id}
                onChange={e => setForm({ ...form, patient_id: e.target.value })}
                className="w-full text-sm border border-research-border rounded-lg px-3 py-2 bg-white focus:outline-none focus:border-research-blue transition-colors"
              >
                <option value="">Select a patient…</option>
                {patients.map(p => (
                  <option key={p.patient_id} value={p.patient_id} disabled={!p.gdpr_consent_given}>
                    {p.display_name}{!p.gdpr_consent_given ? ' (consent withdrawn)' : ''}
                  </option>
                ))}
              </select>
              {patients.length === 0 && (
                <p className="text-[11px] text-amber-600 mt-1">No patients yet — create one on the Patients page first.</p>
              )}
            </div>
            <div>
              <label className="block text-xs font-semibold text-research-muted uppercase tracking-wider mb-1 flex items-center gap-1"><Cpu className="w-3 h-3"/> Runtime Backend</label>
              <select 
                value={form.backend}
                onChange={e => setForm({...form, backend: e.target.value})}
                className="w-full text-sm border border-research-border rounded-lg px-3 py-2 bg-white focus:outline-none focus:border-research-blue transition-colors"
              >
                <option value="auto">Auto-Detect (OpenXR/Oculus)</option>
                <option value="openxr">OpenXR Native</option>
                <option value="oculus">Oculus Native API</option>
                <option value="steamvr">SteamVR (OpenVR)</option>
                <option value="quest_udp">Quest UDP Stream (Network)</option>
              </select>
            </div>

            {form.backend === 'quest_udp' && (
              <div>
                <label className="block text-xs font-semibold text-research-muted uppercase tracking-wider mb-1 flex items-center gap-1"><Network className="w-3 h-3"/> Binding Port (UDP)</label>
                <input 
                  type="number" 
                  value={form.port}
                  onChange={e => setForm({...form, port: Number(e.target.value)})}
                  className="w-full text-sm border border-research-border rounded-lg px-3 py-2 bg-white focus:outline-none focus:border-research-blue transition-colors font-mono"
                />
              </div>
            )}

            <div>
              <label className="block text-xs font-semibold text-research-muted uppercase tracking-wider mb-1 flex items-center gap-1"><Server className="w-3 h-3"/> Central Server Address</label>
              <input 
                type="text" 
                value={form.central_server_url}
                onChange={e => setForm({...form, central_server_url: e.target.value})}
                placeholder="http://192.168.1.X:9000"
                className="w-full text-sm border border-research-border rounded-lg px-3 py-2 bg-white focus:outline-none focus:border-research-blue transition-colors font-mono"
              />
              <p className="text-[11px] text-research-muted mt-1">Where completed sessions are synced after recording stops.</p>
            </div>
          </div>

          <div className="mt-auto pt-6 border-t border-research-border">
            <label className="flex items-start gap-3 cursor-pointer group">
              <div className="mt-0.5">
                <input 
                  type="checkbox" 
                  checked={form.gdpr_consent}
                  onChange={e => setForm({...form, gdpr_consent: e.target.checked})}
                  className="w-4 h-4 rounded border-research-border text-research-blue focus:ring-research-blue bg-white cursor-pointer"
                />
              </div>
              <div>
                <span className="text-sm font-medium text-research-graphite group-hover:text-research-blue transition-colors">Explicit Subject Consent Confirmed</span>
                <p className="text-xs text-research-muted mt-1 leading-relaxed">By checking this box, the researcher verifies that the subject has provided informed GDPR consent for the collection and processing of biophysical telemetry, including spatial kinematics and eye-tracking profiles.</p>
              </div>
            </label>
          </div>
        </div>

        {/* Action Panel */}
        <div className="glass-panel p-6 flex flex-col justify-between">
          <div>
            <h3 className="font-semibold text-research-graphite border-b border-research-border pb-2 flex items-center gap-2">
              <ShieldAlert className="w-4 h-4 text-amber-500" /> Operational Status
            </h3>
            
            {error && (
              <div className="mt-4 p-3 bg-red-50 border border-red-100 rounded-lg text-sm text-red-600 flex items-start gap-2">
                <ShieldAlert className="w-4 h-4 mt-0.5 flex-shrink-0" />
                <p>{error}</p>
              </div>
            )}

            {!isRecording ? (
              <div className="mt-6 space-y-3">
                <div className="flex justify-between items-center text-sm">
                  <span className="text-research-muted">Engine State</span>
                  <span className="font-mono text-slate-500 bg-slate-100 px-2 rounded">IDLE</span>
                </div>
                <div className="flex justify-between items-center text-sm">
                  <span className="text-research-muted">Target Output</span>
                  <span className="font-mono text-research-graphite">/Sessions/</span>
                </div>
              </div>
            ) : (
              <div className="mt-6 space-y-3 border border-research-border p-4 rounded-xl bg-white/50 shadow-inner">
                <div className="flex justify-between items-center text-sm">
                  <span className="text-research-muted">Engine State</span>
                  <span className="font-mono text-red-500 bg-red-50 px-2 rounded border border-red-100 animate-pulse">RECORDING</span>
                </div>
                <div className="flex justify-between items-center text-sm">
                  <span className="text-research-muted">Subject Binding</span>
                  <span className="font-mono text-research-blue">{form.subject_id}</span>
                </div>
                <div className="flex justify-between items-center text-sm">
                  <span className="text-research-muted">Active Pipeline</span>
                  <span className="font-mono text-research-graphite">{form.backend.toUpperCase()}</span>
                </div>
                <div className="flex justify-between items-center text-sm">
                  <span className="text-research-muted">Sync Target</span>
                  <span className="font-mono text-research-graphite truncate max-w-[160px]">{form.central_server_url}</span>
                </div>
              </div>
            )}
          </div>

          {!isRecording ? (
            <button 
              onClick={handleStart}
              disabled={isLoading || !form.gdpr_consent}
              className="w-full py-3 rounded-lg font-medium bg-research-blue text-white shadow-sm hover:shadow hover:bg-blue-600 transition-all disabled:opacity-50 flex items-center justify-center gap-2"
            >
              <PlayCircle className="w-5 h-5" /> 
              {isLoading ? 'Initializing Hardware...' : 'Initialize Telemetry Engine'}
            </button>
          ) : (
            <button 
              onClick={handleStop}
              disabled={isLoading}
              className="w-full py-3 rounded-lg font-medium bg-red-500 text-white shadow-sm hover:shadow hover:bg-red-600 transition-all flex items-center justify-center gap-2"
            >
              <StopCircle className="w-5 h-5" /> 
              {isLoading ? 'Sealing Parquet Buffers...' : 'Terminate Recording'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};