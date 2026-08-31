// src/frontend/VRTelemetry/src/pages/Activation.tsx

import React, { useState } from 'react';
import { KeyRound, ArrowRight, AlertCircle, ShieldCheck } from 'lucide-react';

interface ActivationProps {
  onActivated: () => void;
}

export const Activation: React.FC<ActivationProps> = ({ onActivated }) => {
  const [licenseKey, setLicenseKey] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleActivate = async () => {
    if (!licenseKey.trim()) {
      setError('Enter the license key provided by your administrator.');
      return;
    }
    setError(null);
    setIsLoading(true);
    try {
      const response = await fetch('http://localhost:8000/api/license/activate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ license_key: licenseKey.trim() }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Activation failed.');
      onActivated();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen w-full items-center justify-center p-6">
      <div className="clay w-full max-w-md p-7">
        <div className="mb-3 flex items-center gap-2.5">
          <div className="clay-xs flex h-[34px] w-[34px] flex-none items-center justify-center"
               style={{ color: 'var(--s1)', borderRadius: 11 }}>
            <ShieldCheck className="h-[17px] w-[17px]" strokeWidth={2.1} />
          </div>
          <div className="text-[15px] font-semibold">Activate This Machine</div>
        </div>
        <p className="mb-5 text-[13px] text-ink-2">
          You're signed in, but this machine isn't licensed yet. Enter the license key
          issued to your lab to enable telemetry acquisition.
        </p>

        <div className="space-y-4">
          <div>
            <label htmlFor="license-key" className="field-label flex items-center gap-1.5">
              <KeyRound className="h-3 w-3" /> License Key
            </label>
            <input
              id="license-key"
              type="text"
              value={licenseKey}
              onChange={e => setLicenseKey(e.target.value.toUpperCase())}
              onKeyDown={e => e.key === 'Enter' && handleActivate()}
              className="field field-mono"
              placeholder="XXXX-XXXX-XXXX-XXXX"
            />
            <p className="mt-1.5 text-[11px] text-ink-3">Keys are uppercased automatically. Enter submits.</p>
          </div>

          <button
            onClick={handleActivate}
            disabled={isLoading}
            className="btn-accent btn-accent-lg w-full justify-center"
          >
            {isLoading ? 'Activating…' : 'Activate'}
            {!isLoading && <ArrowRight className="h-4 w-4" />}
          </button>

          {error && (
            <div className="notice tone-2 items-start text-[13px]" role="alert">
              <AlertCircle className="mt-0.5 h-4 w-4 flex-none text-tone" />
              <p className="m-0 flex-1 text-ink-2">{error}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
