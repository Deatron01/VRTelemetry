// src/frontend/VRTelemetry/src/pages/Login.tsx

import React, { useState } from 'react';
import { Activity, Mail, Lock, Building2, User, ArrowRight, AlertCircle } from 'lucide-react';

interface LoginProps {
  onAuthenticated: (session: { email: string; display_name: string }) => void;
}

export const Login: React.FC<LoginProps> = ({ onAuthenticated }) => {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [form, setForm] = useState({
    email: '',
    password: '',
    org_name: '',
    display_name: '',
  });

  const handleSubmit = async () => {
    setError(null);

    if (!form.email || !form.password) {
      setError('Email and password are required.');
      return;
    }
    if (mode === 'register' && !form.org_name) {
      setError('Organization / lab name is required to register.');
      return;
    }

    setIsLoading(true);
    try {
      const endpoint = mode === 'login' ? '/api/auth/login' : '/api/auth/register';
      const body = mode === 'login'
        ? { email: form.email, password: form.password }
        : { email: form.email, password: form.password, org_name: form.org_name, display_name: form.display_name };

      const response = await fetch(`http://localhost:8000${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Something went wrong.');

      if (mode === 'register') {
        // Registration succeeded — flip to login so they authenticate with the same flow
        setMode('login');
        setForm(f => ({ ...f, password: '' }));
        setError(null);
        return;
      }

      onAuthenticated({ email: data.email, display_name: data.display_name });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-[#f1f5f9]">
      <div className="glass-panel p-8 w-full max-w-md">
        <div className="flex items-center gap-2 text-research-graphite font-semibold text-lg mb-1">
          <Activity className="w-6 h-6 text-research-blue" />
          VRTelemetry <span className="font-light text-research-muted ml-1">Research Studio</span>
        </div>
        <p className="text-sm text-research-muted mb-6">
          {mode === 'login' ? 'Sign in to access your telemetry workspace.' : 'Register your lab to get started.'}
        </p>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-100 rounded-lg text-sm text-red-600 flex items-start gap-2">
            <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
            <p>{error}</p>
          </div>
        )}

        <div className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-research-muted uppercase tracking-wider mb-1 flex items-center gap-1">
              <Mail className="w-3 h-3" /> Email
            </label>
            <input
              type="email"
              value={form.email}
              onChange={e => setForm({ ...form, email: e.target.value })}
              className="w-full text-sm border border-research-border rounded-lg px-3 py-2 bg-white focus:outline-none focus:border-research-blue transition-colors"
              placeholder="researcher@university.edu"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-research-muted uppercase tracking-wider mb-1 flex items-center gap-1">
              <Lock className="w-3 h-3" /> Password
            </label>
            <input
              type="password"
              value={form.password}
              onChange={e => setForm({ ...form, password: e.target.value })}
              onKeyDown={e => e.key === 'Enter' && handleSubmit()}
              className="w-full text-sm border border-research-border rounded-lg px-3 py-2 bg-white focus:outline-none focus:border-research-blue transition-colors"
              placeholder="••••••••"
            />
          </div>

          {mode === 'register' && (
            <>
              <div>
                <label className="block text-xs font-semibold text-research-muted uppercase tracking-wider mb-1 flex items-center gap-1">
                  <Building2 className="w-3 h-3" /> Organization / Lab
                </label>
                <input
                  type="text"
                  value={form.org_name}
                  onChange={e => setForm({ ...form, org_name: e.target.value })}
                  className="w-full text-sm border border-research-border rounded-lg px-3 py-2 bg-white focus:outline-none focus:border-research-blue transition-colors"
                  placeholder="Cognitive Systems Lab"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-research-muted uppercase tracking-wider mb-1 flex items-center gap-1">
                  <User className="w-3 h-3" /> Display Name (optional)
                </label>
                <input
                  type="text"
                  value={form.display_name}
                  onChange={e => setForm({ ...form, display_name: e.target.value })}
                  className="w-full text-sm border border-research-border rounded-lg px-3 py-2 bg-white focus:outline-none focus:border-research-blue transition-colors"
                  placeholder="Dr. Jane Smith"
                />
              </div>
            </>
          )}

          <button
            onClick={handleSubmit}
            disabled={isLoading}
            className="w-full py-3 rounded-lg font-medium bg-research-blue text-white shadow-sm hover:shadow hover:bg-blue-600 transition-all disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {isLoading ? 'Please wait...' : mode === 'login' ? 'Sign In' : 'Create Account'}
            {!isLoading && <ArrowRight className="w-4 h-4" />}
          </button>
        </div>

        <div className="mt-5 text-center text-sm text-research-muted">
          {mode === 'login' ? (
            <>Don't have an account?{' '}
              <button onClick={() => { setMode('register'); setError(null); }} className="text-research-blue font-medium hover:underline">
                Register your lab
              </button>
            </>
          ) : (
            <>Already registered?{' '}
              <button onClick={() => { setMode('login'); setError(null); }} className="text-research-blue font-medium hover:underline">
                Sign in
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
};