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
    <div className="min-h-screen w-full flex items-center justify-center bg-[#f1f5f9]">
      <div className="glass-panel p-8 w-full max-w-md">
        <div className="flex items-center gap-2 text-research-graphite font-semibold text-lg mb-1">
          <ShieldCheck className="w-6 h-6 text-research-blue" />
          Activate This Machine
        </div>
        <p className="text-sm text-research-muted mb-6">
          You're signed in, but this machine isn't licensed yet. Enter the license key
          issued to your lab to enable telemetry acquisition.
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
              <KeyRound className="w-3 h-3" /> License Key
            </label>
            <input
              type="text"
              value={licenseKey}
              onChange={e => setLicenseKey(e.target.value.toUpperCase())}
              onKeyDown={e => e.key === 'Enter' && handleActivate()}
              className="w-full text-sm border border-research-border rounded-lg px-3 py-2 bg-white font-mono focus:outline-none focus:border-research-blue transition-colors"
              placeholder="XXXX-XXXX-XXXX-XXXX"
            />
          </div>

          <button
            onClick={handleActivate}
            disabled={isLoading}
            className="w-full py-3 rounded-lg font-medium bg-research-blue text-white shadow-sm hover:shadow hover:bg-blue-600 transition-all disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {isLoading ? 'Activating...' : 'Activate'}
            {!isLoading && <ArrowRight className="w-4 h-4" />}
          </button>
        </div>
      </div>
    </div>
  );
};