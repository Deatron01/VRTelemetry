// src/frontend/VRTelemetry/src/pages/Login.tsx

import React, { useState } from 'react';
import { Activity, Mail, Lock, Building2, User, ArrowRight, AlertCircle, Server } from 'lucide-react';
import { HubPairing } from '../components/HubPairing';

interface LoginProps {
  onAuthenticated: (session: { email: string; display_name: string }) => void;
}

export const Login: React.FC<LoginProps> = ({ onAuthenticated }) => {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Signing in goes through the hub, so a workstation that has never been
  // connected to one needs this before anything else works.
  const [showPairing, setShowPairing] = useState(false);

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
    <div className="flex min-h-screen w-full items-center justify-center p-6">
      <div className="clay w-full max-w-md p-7">
        <div className="mb-1 flex items-center gap-2.5">
          <div className="clay-xs flex h-[34px] w-[34px] flex-none items-center justify-center"
               style={{ color: 'var(--s1)', borderRadius: 11 }}>
            <Activity className="h-[17px] w-[17px]" strokeWidth={2.1} />
          </div>
          <div className="text-[15px] font-semibold">
            VRTelemetry <span className="font-normal text-ink-3">Research Studio</span>
          </div>
        </div>
        <p className="mb-5 mt-2 text-[13px] text-ink-2">
          {mode === 'login' ? 'Sign in to access your telemetry workspace.' : 'Register your lab to get started.'}
        </p>

        <div className="seg mb-5 w-full" role="group" aria-label="Authentication mode">
          <button
            onClick={() => { setMode('login'); setError(null); }}
            aria-pressed={mode === 'login'}
            className={`flex-1 ${mode === 'login' ? 'seg-item is-active' : 'seg-item'}`}
          >
            Sign in
          </button>
          <button
            onClick={() => { setMode('register'); setError(null); }}
            aria-pressed={mode === 'register'}
            className={`flex-1 ${mode === 'register' ? 'seg-item is-active' : 'seg-item'}`}
          >
            Register a lab
          </button>
        </div>

        {error && (
          <div className="notice tone-2 mb-4 items-start text-[13px]" role="alert">
            <AlertCircle className="mt-0.5 h-4 w-4 flex-none text-tone" />
            <p className="m-0 flex-1 text-ink-2">{error}</p>
          </div>
        )}

        <div className="space-y-4">
          <div>
            <label htmlFor="auth-email" className="field-label flex items-center gap-1.5">
              <Mail className="h-3 w-3" /> Email
            </label>
            <input
              id="auth-email"
              type="email"
              value={form.email}
              onChange={e => setForm({ ...form, email: e.target.value })}
              className="field"
              placeholder="researcher@university.edu"
            />
          </div>

          <div>
            <label htmlFor="auth-password" className="field-label flex items-center gap-1.5">
              <Lock className="h-3 w-3" /> Password
            </label>
            <input
              id="auth-password"
              type="password"
              value={form.password}
              onChange={e => setForm({ ...form, password: e.target.value })}
              onKeyDown={e => e.key === 'Enter' && handleSubmit()}
              className="field"
              placeholder="••••••••"
            />
          </div>

          {mode === 'register' && (
            <>
              <div>
                <label htmlFor="auth-org" className="field-label flex items-center gap-1.5">
                  <Building2 className="h-3 w-3" /> Organization / Lab
                </label>
                <input
                  id="auth-org"
                  type="text"
                  value={form.org_name}
                  onChange={e => setForm({ ...form, org_name: e.target.value })}
                  className="field"
                  placeholder="Cognitive Systems Lab"
                />
              </div>
              <div>
                <label htmlFor="auth-name" className="field-label flex items-center gap-1.5">
                  <User className="h-3 w-3" /> Principal Investigator (optional)
                </label>
                <input
                  id="auth-name"
                  type="text"
                  value={form.display_name}
                  onChange={e => setForm({ ...form, display_name: e.target.value })}
                  className="field"
                  placeholder="Dr. Jane Smith"
                />
              </div>
            </>
          )}

          <button
            onClick={handleSubmit}
            disabled={isLoading}
            className="btn-accent btn-accent-lg w-full justify-center"
          >
            {isLoading ? 'Please wait…' : mode === 'login' ? 'Sign In' : 'Create Account'}
            {!isLoading && <ArrowRight className="h-4 w-4" />}
          </button>
        </div>

        <p className="mt-5 text-center text-[12.5px] text-ink-3">
          {mode === 'login' ? (
            <>No account yet?{' '}
              <button onClick={() => { setMode('register'); setError(null); }} className="font-medium" style={{ color: 'var(--s1)' }}>
                Register your lab
              </button>
            </>
          ) : (
            <>Already registered?{' '}
              <button onClick={() => { setMode('login'); setError(null); }} className="font-medium" style={{ color: 'var(--s1)' }}>
                Sign in
              </button>
            </>
          )}
        </p>

        <div className="mt-5 pt-4" style={{ borderTop: '1px solid var(--hair)' }}>
          <button
            type="button"
            onClick={() => setShowPairing(v => !v)}
            aria-expanded={showPairing}
            className="flex w-full items-center gap-1.5 text-[12.5px] text-ink-3"
          >
            <Server className="h-3.5 w-3.5" />
            {showPairing ? 'Hide hub connection' : 'Connect to a hub on another machine…'}
          </button>
          {showPairing && (
            <div className="mt-3">
              <HubPairing onPaired={() => setError(null)} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
