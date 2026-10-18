// src/frontend/VRTelemetry/src/components/HubPairing.tsx
//
// Connect this workstation to a hub on another machine with the six-digit code
// the hub's admin UI shows ("Pair a Workstation"). Replaces copying hub-ca.pem
// and config.toml from the hub's workstation kit by hand: the backend fetches
// the hub's CA certificate, checks it against the code, and writes both files
// into the data root (POST /api/config/central-server/pair).

import React, { useState } from 'react';
import { KeyRound, Link2, CheckCircle2, AlertCircle } from 'lucide-react';

const API = 'http://localhost:8000';

interface PairResult {
  url: string;
  fingerprint: string;
  applied_now: boolean;
}

interface HubPairingProps {
  /** Pre-fills the address field, e.g. with the saved hub address. */
  initialUrl?: string;
  onPaired?: (url: string) => void;
}

// The backend answers errors as { detail: { reason, message } }; other routes
// still use a plain string, so accept both.
function errorMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return String((detail as { message: unknown }).message);
  }
  return fallback;
}

export const HubPairing: React.FC<HubPairingProps> = ({ initialUrl = '', onPaired }) => {
  const [url, setUrl] = useState(initialUrl);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PairResult | null>(null);

  const digits = code.replace(/\D/g, '');
  const canPair = !busy && url.trim().length > 0 && digits.length === 6;

  const pair = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const response = await fetch(`${API}/api/config/central-server/pair`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ central_server_url: url.trim(), code: digits }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(errorMessage(body, `Pairing failed (HTTP ${response.status}).`));
      setResult(body as PairResult);
      setCode('');
      onPaired?.((body as PairResult).url);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Pairing failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <div>
        <label htmlFor="pair-url" className="field-label flex items-center gap-1.5">
          <Link2 className="h-3 w-3" /> Hub address
        </label>
        <input
          id="pair-url"
          type="text"
          value={url}
          onChange={e => setUrl(e.target.value)}
          placeholder="https://192.168.1.50:9000"
          className="field field-mono"
        />
      </div>
      <div>
        <label htmlFor="pair-code" className="field-label flex items-center gap-1.5">
          <KeyRound className="h-3 w-3" /> Pairing code
        </label>
        <div className="flex gap-2">
          <input
            id="pair-code"
            type="text"
            inputMode="numeric"
            autoComplete="off"
            value={code}
            onChange={e => setCode(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && canPair && pair()}
            placeholder="123 456"
            maxLength={9}
            className="field field-mono flex-1 tracking-widest"
          />
          <button type="button" onClick={pair} disabled={!canPair} className="btn-clay flex-none whitespace-nowrap">
            {busy ? 'Pairing…' : 'Pair'}
          </button>
        </div>
        <p className="mt-1.5 text-[11px] text-ink-3">
          An administrator generates the code in the hub's admin UI under “Pair a Workstation”.
          It works once and expires after ten minutes.
        </p>
      </div>

      {error && (
        <div className="notice tone-2 items-start text-[12.5px]" role="alert">
          <AlertCircle className="mt-0.5 h-4 w-4 flex-none text-tone" />
          <p className="m-0 flex-1 text-ink-2">{error}</p>
        </div>
      )}
      {result && (
        <div className="notice tone-1 items-start text-[12.5px]" role="status">
          <CheckCircle2 className="mt-0.5 h-4 w-4 flex-none" style={{ color: 'var(--s1)' }} />
          <div className="m-0 flex-1 text-ink-2">
            Paired with {result.url}. This workstation now trusts the hub's certificate
            {result.applied_now ? '.' : ' after the app is restarted.'}
            <div className="mt-1 break-all text-[10.5px] text-ink-3 mono">
              CA fingerprint {result.fingerprint}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
