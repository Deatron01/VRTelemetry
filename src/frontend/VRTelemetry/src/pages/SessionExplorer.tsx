import React, { useEffect, useState } from 'react';
import { Database, Search, User, AlertCircle, X, Cpu, Edit2, Save, PlayCircle, ClipboardList, Loader2 } from 'lucide-react';
import { useTelemetryStore } from '../store/useTelemetryStore';
import { TelemetryParser } from '../services/TelemetryParser';
import { PostSessionQuestionnaire } from '../components/PostSessionQuestionnaire';

interface SessionExplorerProps {
  onNavigate?: (route: string) => void;
}

interface SessionRecord {
  session_id: string;
  patient_id: string | null;
  patient_display_name: string | null;
  start_timestamp_utc: string;
  subject_id: string;
  hmd_model: string;
  tracking_space_type: string;
  total_dropped_frames: number;
  session_rating: number;
}

export const SessionExplorer: React.FC<SessionExplorerProps> = ({ onNavigate }) => {
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const [selectedSession, setSelectedSession] = useState<any | null>(null);
  const [isDetailsLoading, setIsDetailsLoading] = useState(false);
  const [isLoadingAnalysis, setIsLoadingAnalysis] = useState<string | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [questionnaireSessionId, setQuestionnaireSessionId] = useState<string | null>(null);
  
  const [query, setQuery] = useState('');

  // Edit State
  const [isEditing, setIsEditing] = useState(false);
  const [editForm, setEditForm] = useState({
    subject_id: '',
    start_timestamp_utc: '',
    subject_vr_exp: '',
    session_rating: 0
  });

  const handleLoadForAnalysis = async (sessionId: string) => {
    setIsLoadingAnalysis(sessionId);
    setAnalysisError(null);
    try {
      const { frames, metadata, metrics } = await TelemetryParser.parseSessionId(sessionId);
      useTelemetryStore.getState().loadSession(frames, metadata, metrics);
      onNavigate?.('overview');
    } catch (err) {
      setAnalysisError(err instanceof Error ? err.message : 'Failed to load session telemetry.');
    } finally {
      setIsLoadingAnalysis(null);
    }
  };

  const fetchSessions = async () => {
    try {
      const response = await fetch('http://localhost:8000/api/sessions');
      if (!response.ok) throw new Error('Database connection failed.');
      const data = await response.json();
      setSessions(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error occurred.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchSessions();
  }, []);

  const handleViewDetails = async (sessionId: string) => {
    setIsDetailsLoading(true);
    try {
      const response = await fetch(`http://localhost:8000/api/sessions/${sessionId}`);
      if (!response.ok) throw new Error('Failed to fetch session details');
      const data = await response.json();
      setSelectedSession(data);
      setEditForm({
        subject_id: data.subject_id,
        start_timestamp_utc: data.start_timestamp_utc,
        subject_vr_exp: data.subject_vr_exp,
        session_rating: data.session_rating
      });
      setIsEditing(false);
    } catch (err) {
      console.error(err);
      alert("Could not load session details. Check console.");
    } finally {
      setIsDetailsLoading(false);
    }
  };

  const handleSaveChanges = async () => {
    try {
      const response = await fetch(`http://localhost:8000/api/sessions/${selectedSession.session_id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editForm)
      });
      
      if (!response.ok) throw new Error('Failed to update session');
      
      // Update local state without needing to refetch the whole modal
      setSelectedSession({ ...selectedSession, ...editForm });
      setIsEditing(false);
      
      // Refetch the background table to show updated data
      fetchSessions();
    } catch (err) {
      console.error(err);
      alert("Failed to save changes.");
    }
  };

  const q = query.trim().toLowerCase();
  const visible = sessions.filter(session => {
    if (!q) return true;
    return [session.subject_id, session.patient_display_name, session.hmd_model, session.session_id]
      .some(field => (field || '').toLowerCase().includes(q));
  });
  const unlinked = sessions.filter(s => !s.patient_display_name).length;

  return (
    <div className="relative mx-auto flex h-full max-w-[1360px] flex-col gap-4">
      <div>
        <h1 className="page-title">Session Explorer</h1>
        <p className="page-sub">Relational query interface for subject and hardware metadata.</p>
      </div>

      {analysisError && (
        <div className="notice tone-2 items-start text-[13px]">
          <AlertCircle className="mt-0.5 h-4 w-4 flex-none text-tone" />
          <p className="m-0 flex-1 text-ink-2">{analysisError}</p>
        </div>
      )}

      <div className="clay flex min-h-0 flex-1 flex-col gap-3 p-3.5">
        <div className="flex flex-wrap items-center gap-3">
          <div className="clay-press flex max-w-[380px] flex-1 items-center gap-2 px-3 py-[7px]" style={{ borderRadius: 11 }}>
            <Search className="h-4 w-4 flex-none text-ink-3" aria-hidden="true" />
            <label htmlFor="session-search" className="sr-only">Filter sessions</label>
            <input
              id="session-search"
              placeholder="Filter by subject, patient or hardware"
              value={query}
              onChange={e => setQuery(e.target.value)}
              className="min-w-0 flex-1 border-none bg-transparent text-[13px] outline-none"
            />
          </div>
          <div className="flex-1" />
          <span className="section-note">
            {sessions.length} session{sessions.length === 1 ? '' : 's'}
            {unlinked > 0 ? ` · ${unlinked} unlinked` : ''}
          </span>
        </div>

        <div className="well min-h-0 flex-1 overflow-hidden" style={{ borderRadius: 12 }}>
          {isLoading ? (
            <p className="py-10 text-center text-[13px] text-ink-3">Loading sessions…</p>
          ) : error ? (
            <div className="flex flex-col items-center gap-2 py-10" style={{ color: 'var(--s2)' }}>
              <AlertCircle className="h-7 w-7" />
              <p className="m-0 text-[13px] font-medium">Backend connection error</p>
            </div>
          ) : visible.length === 0 ? (
            <p className="py-10 text-center text-[13px] text-ink-3">
              {sessions.length === 0 ? 'No sessions recorded yet.' : 'No sessions match this filter.'}
            </p>
          ) : (
            <div className="h-full overflow-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Session UUID</th>
                    <th>Patient</th>
                    <th>Date (UTC)</th>
                    <th>Subject</th>
                    <th>Hardware</th>
                    <th style={{ textAlign: 'right' }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map(session => (
                    <tr key={session.session_id}>
                      <td className="num text-ink-3">{session.session_id.split('-')[0]}…</td>
                      <td>
                        {session.patient_display_name
                          ? <span style={{ color: 'var(--ink)', fontWeight: 500 }}>{session.patient_display_name}</span>
                          : <span className="italic text-ink-3">Unlinked</span>}
                      </td>
                      <td className="num">{session.start_timestamp_utc}</td>
                      <td className="num" style={{ color: 'var(--ink)' }}>{session.subject_id}</td>
                      <td>{session.hmd_model}</td>
                      <td>
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => handleLoadForAnalysis(session.session_id)}
                            disabled={isLoadingAnalysis === session.session_id}
                            aria-label={`Load session ${session.session_id} for analysis`}
                            className="btn-clay"
                            style={{ color: 'var(--s6)', fontWeight: 600 }}
                          >
                            {isLoadingAnalysis === session.session_id
                              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              : <PlayCircle className="h-3.5 w-3.5" />}
                            Analyze
                          </button>
                          <button
                            onClick={() => setQuestionnaireSessionId(session.session_id)}
                            aria-label={`Complete post-session questionnaire for ${session.session_id}`}
                            className="btn-clay"
                            style={{ color: 'var(--s5)', fontWeight: 600 }}
                          >
                            <ClipboardList className="h-3.5 w-3.5" /> Questionnaire
                          </button>
                          <button
                            onClick={() => handleViewDetails(session.session_id)}
                            disabled={isDetailsLoading}
                            aria-label={`View details for session ${session.session_id}`}
                            className="btn-clay"
                            style={{ color: 'var(--s1)', fontWeight: 600 }}
                          >
                            Details →
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Details & Edit Modal */}
      {selectedSession && (
        <div className="modal-backdrop" style={{ position: 'absolute' }} role="dialog" aria-modal="true" aria-labelledby="session-record-title">
          <div className="modal-card flex max-w-3xl flex-col overflow-hidden p-0">
            
            <div className="flex items-center justify-between gap-4 px-5 py-4" style={{ borderBottom: '1px solid var(--hair)' }}>
              <div>
                <h2 id="session-record-title" className="m-0 flex items-center gap-2 text-[16px] font-semibold">
                  <Database className="h-[18px] w-[18px]" style={{ color: 'var(--s1)' }} /> Session Record
                </h2>
                <p className="mono m-0 mt-1 text-[11px] text-ink-3">{selectedSession.session_id}</p>
              </div>
              <div className="flex items-center gap-2">
                {!isEditing ? (
                  <button onClick={() => setIsEditing(true)} className="btn-clay" style={{ color: 'var(--s1)', fontWeight: 600 }}>
                    <Edit2 className="w-4 h-4" /> Edit Parameters
                  </button>
                ) : (
                  <button onClick={handleSaveChanges} className="btn-accent">
                    <Save className="w-4 h-4" /> Save Changes
                  </button>
                )}
                <button onClick={() => setSelectedSession(null)} aria-label="Close session record" className="btn-ghost">
                  <X className="h-[18px] w-[18px]" />
                </button>
              </div>
            </div>

            <div className="flex-1 space-y-5 overflow-y-auto p-5">
              {/* Editable Profile Data */}
              <div className={isEditing ? 'well p-4' : 'p-0'}>
                <h3 className="section-title mb-3 flex items-center gap-2 pb-1.5" style={{ borderBottom: '1px solid var(--hair)' }}>
                  <User className="h-4 w-4" /> Subject Profile &amp; Timing
                </h3>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <div>
                    <span className="summary-key mb-1.5 block">Subject ID</span>
                    {isEditing ? (
                      <input 
                        className="field" 
                        value={editForm.subject_id} 
                        onChange={e => setEditForm({...editForm, subject_id: e.target.value})} 
                      />
                    ) : <span className="font-medium">{selectedSession.subject_id}</span>}
                  </div>
                  <div>
                    <span className="summary-key mb-1.5 block">Date / Timestamp (UTC)</span>
                    {isEditing ? (
                      <input 
                        className="field" 
                        value={editForm.start_timestamp_utc} 
                        onChange={e => setEditForm({...editForm, start_timestamp_utc: e.target.value})} 
                      />
                    ) : <span className="font-medium">{selectedSession.start_timestamp_utc}</span>}
                  </div>
                  <div>
                    <span className="summary-key mb-1.5 block">VR Experience Level</span>
                    {isEditing ? (
                      <input 
                        className="field" 
                        value={editForm.subject_vr_exp} 
                        onChange={e => setEditForm({...editForm, subject_vr_exp: e.target.value})} 
                      />
                    ) : <span className="font-medium">{selectedSession.subject_vr_exp}</span>}
                  </div>
                  <div>
                    <span className="summary-key mb-1.5 block">Overall Session Rating (0-10)</span>
                    {isEditing ? (
                      <input 
                        type="number"
                        className="field" 
                        value={editForm.session_rating} 
                        onChange={e => setEditForm({...editForm, session_rating: Number(e.target.value)})} 
                      />
                    ) : <span className="font-medium" style={{ color: 'var(--s1)' }}>{selectedSession.session_rating} / 10</span>}
                  </div>
                </div>
              </div>

              {/* Read-Only Hardware Data */}
              <div>
                <h3 className="section-title mb-3 flex items-center gap-2 pb-1.5" style={{ borderBottom: '1px solid var(--hair)' }}>
                  <Cpu className="h-4 w-4" /> Hardware &amp; Telemetry <span className="font-normal normal-case tracking-normal text-ink-3">— read only</span>
                </h3>
                <div className="well grid grid-cols-1 gap-4 p-3.5 sm:grid-cols-3">
                  <div><span className="summary-key mb-1.5 block">HMD Model</span><span className="font-medium">{selectedSession.hmd_model}</span></div>
                  <div><span className="summary-key mb-1.5 block">Refresh Rate</span><span className="font-medium">{selectedSession.hmd_refresh_rate} Hz</span></div>
                  <div><span className="summary-key mb-1.5 block">Eye Tracking</span><span className="font-medium" style={{ color: 'var(--s6)' }}>Enabled</span></div>
                </div>
              </div>

            </div>
          </div>
        </div>
      )}
      {questionnaireSessionId && (
        <PostSessionQuestionnaire
          sessionId={questionnaireSessionId}
          onClose={() => setQuestionnaireSessionId(null)}
          onSaved={() => { setQuestionnaireSessionId(null); fetchSessions(); }}
        />
      )}
    </div>
  );
};