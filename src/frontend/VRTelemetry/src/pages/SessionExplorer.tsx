import React, { useEffect, useState } from 'react';
import { Database, Search, User, HardDrive, AlertCircle, X, Activity, Cpu, Edit2, Save } from 'lucide-react';

interface SessionRecord {
  session_id: string;
  start_timestamp_utc: string;
  subject_id: string;
  hmd_model: string;
  tracking_space_type: string;
  total_dropped_frames: number;
  session_rating: number;
}

export const SessionExplorer = () => {
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const [selectedSession, setSelectedSession] = useState<any | null>(null);
  const [isDetailsLoading, setIsDetailsLoading] = useState(false);
  
  // Edit State
  const [isEditing, setIsEditing] = useState(false);
  const [editForm, setEditForm] = useState({
    subject_id: '',
    start_timestamp_utc: '',
    subject_vr_exp: '',
    session_rating: 0
  });

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

  return (
    <div className="max-w-7xl mx-auto space-y-6 flex flex-col h-[calc(100vh-140px)] relative">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-3">
          <Database className="w-8 h-8 text-research-graphite" />
          <div>
            <h1 className="text-2xl font-semibold text-research-graphite">Session Explorer</h1>
            <p className="text-sm text-research-muted">Relational query interface for subject and hardware metadata.</p>
          </div>
        </div>
      </div>

      <div className="glass-panel overflow-hidden flex flex-col flex-1">
        {isLoading ? (
          <div className="flex-1 flex items-center justify-center text-research-muted">
            Loading...
          </div>
        ) : error ? (
          <div className="flex-1 flex flex-col items-center justify-center text-red-500 gap-2">
            <AlertCircle className="w-8 h-8" />
            <p className="font-medium">Backend Connection Error</p>
          </div>
        ) : (
          <div className="overflow-auto flex-1 p-0">
            <table className="w-full text-sm text-left">
              <thead className="text-xs text-research-muted uppercase bg-slate-50/50 sticky top-0 backdrop-blur-md border-b border-research-border">
                <tr>
                  <th className="px-6 py-4 font-medium tracking-wider">Session UUID</th>
                  <th className="px-6 py-4 font-medium tracking-wider">Date (UTC)</th>
                  <th className="px-6 py-4 font-medium tracking-wider">Subject</th>
                  <th className="px-6 py-4 font-medium tracking-wider">Hardware</th>
                  <th className="px-6 py-4 font-medium tracking-wider text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-research-border">
                {sessions.map(session => (
                  <tr key={session.session_id} className="hover:bg-slate-50/50 transition-colors group">
                    <td className="px-6 py-4 font-mono text-xs">{session.session_id.split('-')[0]}...</td>
                    <td className="px-6 py-4">{session.start_timestamp_utc}</td>
                    <td className="px-6 py-4 font-medium">{session.subject_id}</td>
                    <td className="px-6 py-4 text-research-muted">{session.hmd_model}</td>
                    <td className="px-6 py-4 text-right">
                      <button 
                        onClick={() => handleViewDetails(session.session_id)}
                        disabled={isDetailsLoading}
                        className="text-research-blue text-xs font-medium opacity-0 group-hover:opacity-100 transition-opacity"
                      >
                        View Details &rarr;
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Details & Edit Modal */}
      {selectedSession && (
        <div className="absolute inset-0 z-50 flex items-center justify-center p-6 bg-slate-900/20 backdrop-blur-sm">
          <div className="bg-white/90 backdrop-blur-xl border border-research-border shadow-2xl rounded-2xl w-full max-w-3xl max-h-full flex flex-col overflow-hidden">
            
            <div className="px-6 py-4 border-b border-research-border flex justify-between items-center bg-white/50">
              <div>
                <h2 className="text-lg font-semibold text-research-graphite flex items-center gap-2">
                  <Database className="w-5 h-5 text-research-blue" /> Session Record
                </h2>
                <p className="text-xs font-mono text-research-muted mt-1">{selectedSession.session_id}</p>
              </div>
              <div className="flex items-center gap-2">
                {!isEditing ? (
                  <button onClick={() => setIsEditing(true)} className="glass-button py-1 px-3 bg-blue-50 text-research-blue border-blue-200">
                    <Edit2 className="w-4 h-4" /> Edit Parameters
                  </button>
                ) : (
                  <button onClick={handleSaveChanges} className="glass-button py-1 px-3 bg-green-50 text-research-green border-green-200">
                    <Save className="w-4 h-4" /> Save Changes
                  </button>
                )}
                <button onClick={() => setSelectedSession(null)} className="p-2 hover:bg-slate-100 rounded-full">
                  <X className="w-5 h-5 text-research-graphite" />
                </button>
              </div>
            </div>

            <div className="p-6 overflow-y-auto flex-1 space-y-6">
              {/* Editable Profile Data */}
              <div className={`p-4 rounded-xl border ${isEditing ? 'bg-blue-50/30 border-blue-200' : 'border-transparent'}`}>
                <h3 className="text-sm font-semibold text-research-graphite uppercase tracking-wider mb-3 flex items-center gap-2 border-b border-slate-200 pb-1">
                  <User className="w-4 h-4" /> Subject Profile & Timing
                </h3>
                <div className="grid grid-cols-2 gap-6">
                  <div>
                    <span className="block text-xs text-research-muted mb-1">Subject ID</span>
                    {isEditing ? (
                      <input 
                        className="w-full text-sm border border-research-border rounded px-2 py-1 bg-white" 
                        value={editForm.subject_id} 
                        onChange={e => setEditForm({...editForm, subject_id: e.target.value})} 
                      />
                    ) : <span className="font-medium">{selectedSession.subject_id}</span>}
                  </div>
                  <div>
                    <span className="block text-xs text-research-muted mb-1">Date / Timestamp (UTC)</span>
                    {isEditing ? (
                      <input 
                        className="w-full text-sm border border-research-border rounded px-2 py-1 bg-white" 
                        value={editForm.start_timestamp_utc} 
                        onChange={e => setEditForm({...editForm, start_timestamp_utc: e.target.value})} 
                      />
                    ) : <span className="font-medium">{selectedSession.start_timestamp_utc}</span>}
                  </div>
                  <div>
                    <span className="block text-xs text-research-muted mb-1">VR Experience Level</span>
                    {isEditing ? (
                      <input 
                        className="w-full text-sm border border-research-border rounded px-2 py-1 bg-white" 
                        value={editForm.subject_vr_exp} 
                        onChange={e => setEditForm({...editForm, subject_vr_exp: e.target.value})} 
                      />
                    ) : <span className="font-medium">{selectedSession.subject_vr_exp}</span>}
                  </div>
                  <div>
                    <span className="block text-xs text-research-muted mb-1">Overall Session Rating (0-10)</span>
                    {isEditing ? (
                      <input 
                        type="number"
                        className="w-full text-sm border border-research-border rounded px-2 py-1 bg-white" 
                        value={editForm.session_rating} 
                        onChange={e => setEditForm({...editForm, session_rating: Number(e.target.value)})} 
                      />
                    ) : <span className="font-medium text-research-blue">{selectedSession.session_rating} / 10</span>}
                  </div>
                </div>
              </div>

              {/* Read-Only Hardware Data */}
              <div>
                <h3 className="text-sm font-semibold text-research-graphite uppercase tracking-wider mb-3 flex items-center gap-2 border-b border-slate-200 pb-1">
                  <Cpu className="w-4 h-4" /> Hardware & Telemetry (Read-Only)
                </h3>
                <div className="grid grid-cols-3 gap-4 opacity-75">
                  <div><span className="block text-xs text-research-muted">HMD Model</span><span className="font-medium">{selectedSession.hmd_model}</span></div>
                  <div><span className="block text-xs text-research-muted">Refresh Rate</span><span className="font-medium">{selectedSession.hmd_refresh_rate} Hz</span></div>
                  <div><span className="block text-xs text-research-muted">Eye Tracking</span><span className="font-medium text-research-green">Enabled</span></div>
                </div>
              </div>

            </div>
          </div>
        </div>
      )}
    </div>
  );
};