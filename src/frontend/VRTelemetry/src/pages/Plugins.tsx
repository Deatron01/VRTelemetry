// src/frontend/VRTelemetry/src/pages/Plugins.tsx
import { useEffect, useState } from 'react';
import {
  Puzzle, Download, Trash2, RefreshCw, AlertCircle, CheckCircle2,
  Loader2, ExternalLink, XCircle, Circle, Play, Square,
} from 'lucide-react';

const API = 'http://localhost:8000';

// Shapes mirror src/central_server/plugin_catalog.py's CatalogEntry.to_dict()
// and src/interfaces/api/routers/plugins.py's _status_dict() exactly -- see
// plugins/PROTOCOL.md #7 for the route contract these are read from.
interface CatalogEntry {
  plugin_id: string;
  name: string;
  description: string;
  repo_url: string;
  ref: string;
  homepage: string | null;
  maintainer: string | null;
}

interface PluginStatus {
  plugin_id: string;
  installed: boolean;
  enabled: boolean;
  running: boolean;
  pid: number | null;
  restarts: number;
  last_exit_code: number | null;
  last_error: string | null;
  name: string | null;
  description: string | null;
  version: string | null;
}

export const Plugins = () => {
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [statuses, setStatuses] = useState<PluginStatus[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // plugin_id currently mid-install/-uninstall, so its row can show a
  // spinner and every button can be disabled without a global lock.
  const [pending, setPending] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [catalogRes, statusRes] = await Promise.all([
        fetch(`${API}/api/plugins/catalog`),
        fetch(`${API}/api/plugins/status`),
      ]);
      if (!catalogRes.ok) {
        const data = await catalogRes.json().catch(() => ({}));
        throw new Error(typeof data.detail === 'string' ? data.detail : 'Failed to load the plugin catalog.');
      }
      if (!statusRes.ok) throw new Error('Failed to load plugin status.');
      setCatalog(await catalogRes.json());
      setStatuses(await statusRes.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const statusFor = (pluginId: string): PluginStatus | undefined =>
    statuses.find(s => s.plugin_id === pluginId);

  const handleInstall = async (entry: CatalogEntry) => {
    setActionError(null);
    setPending(entry.plugin_id);
    try {
      const res = await fetch(`${API}/api/plugins/install`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plugin_id: entry.plugin_id }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(typeof data.detail === 'string' ? data.detail : `Could not install '${entry.name}'.`);
      }
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Unknown error.');
    } finally {
      setPending(null);
    }
  };

  const handleUninstall = async (status: PluginStatus) => {
    if (!confirm(
      `Uninstall '${status.name || status.plugin_id}'? This stops the plugin process and removes it from ` +
      'this workstation’s registry. Recording is unaffected either way -- plugins are never on the ' +
      'critical path (see plugins/PROTOCOL.md).'
    )) return;
    setActionError(null);
    setPending(status.plugin_id);
    try {
      const res = await fetch(`${API}/api/plugins/uninstall`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plugin_id: status.plugin_id }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(typeof data.detail === 'string' ? data.detail : `Could not uninstall '${status.plugin_id}'.`);
      }
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Unknown error.');
    } finally {
      setPending(null);
    }
  };

  // Pause/resume the plugin's process without touching its installation --
  // distinct from Install/Uninstall above, which clone/discard it entirely.
  // See POST /api/plugins/start and /stop (src/plugin_manager/manager.py's
  // start_plugin/stop_plugin).
  const handleStart = async (status: PluginStatus) => {
    setActionError(null);
    setPending(status.plugin_id);
    try {
      const res = await fetch(`${API}/api/plugins/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plugin_id: status.plugin_id }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(typeof data.detail === 'string' ? data.detail : `Could not start '${status.plugin_id}'.`);
      }
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Unknown error.');
    } finally {
      setPending(null);
    }
  };

  const handleStop = async (status: PluginStatus) => {
    setActionError(null);
    setPending(status.plugin_id);
    try {
      const res = await fetch(`${API}/api/plugins/stop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plugin_id: status.plugin_id }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(typeof data.detail === 'string' ? data.detail : `Could not stop '${status.plugin_id}'.`);
      }
      await load();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Unknown error.');
    } finally {
      setPending(null);
    }
  };

  const counts = {
    catalog: catalog.length,
    installed: statuses.filter(s => s.installed).length,
    running: statuses.filter(s => s.running).length,
    errors: statuses.filter(s => !!s.last_error).length,
  };

  return (
    <div className="mx-auto flex max-w-[1360px] flex-col gap-4">

      <div className="flex items-end justify-between gap-6">
        <div>
          <h1 className="page-title">Plugin Catalog</h1>
          <p className="page-sub" style={{ maxWidth: '88ch' }}>
            Out-of-process subscribers to the Core Hub's live telemetry (medical analytics, a ROS/Unity bridge,
            and anything else on the operator-approved list below). Installing or uninstalling a plugin never
            touches the recording path -- see <span className="mono">plugins/PROTOCOL.md</span>.
          </p>
        </div>
        <button className="btn-clay flex-none" onClick={() => load()} disabled={isLoading}>
          <RefreshCw className={isLoading ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} /> Refresh
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-4">
        <div className="clay p-3.5">
          <div className="stat-label mb-1.5">Approved plugins</div>
          <div className="stat-value">{counts.catalog}</div>
        </div>
        <div className="clay p-3.5">
          <div className="stat-label mb-1.5">Installed</div>
          <div className="stat-value" style={{ color: 'var(--s1)' }}>{counts.installed}</div>
        </div>
        <div className="clay p-3.5">
          <div className="stat-label mb-1.5">Running</div>
          <div className="stat-value" style={{ color: 'var(--s6)' }}>{counts.running}</div>
        </div>
        <div className="clay p-3.5" style={{ borderLeft: counts.errors ? '3px solid var(--s2)' : undefined }}>
          <div className="stat-label mb-1.5">Errors</div>
          <div className="stat-value" style={{ color: counts.errors ? 'var(--s2)' : undefined }}>{counts.errors}</div>
        </div>
      </div>

      {actionError && (
        <div className="notice tone-2 items-start text-[13px]">
          <AlertCircle className="mt-0.5 h-4 w-4 flex-none text-tone" /><p>{actionError}</p>
        </div>
      )}

      <div className="clay flex flex-col gap-3 p-3.5">
        <div className="flex items-center gap-2">
          <Puzzle className="h-4 w-4 text-ink-3" />
          <p className="section-title m-0">Approved Catalog</p>
        </div>
        <div className="well overflow-hidden" style={{ borderRadius: 12 }}>
          {isLoading ? (
            <p className="py-10 text-center text-[13px] text-ink-3">Loading catalog…</p>
          ) : error ? (
            <div className="flex flex-col items-center gap-2 py-10" style={{ color: 'var(--s2)' }}>
              <AlertCircle className="h-7 w-7" />
              <p className="m-0 text-[13px] font-medium">{error}</p>
            </div>
          ) : catalog.length === 0 ? (
            <p className="py-10 text-center text-[13px] text-ink-3">
              No central server is configured, or it has no approved plugins listed yet.
            </p>
          ) : (
            <div className="max-h-[40vh] overflow-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Description</th>
                    <th>Ref</th>
                    <th>Maintainer</th>
                    <th style={{ textAlign: 'right' }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {catalog.map(entry => {
                    const status = statusFor(entry.plugin_id);
                    const isPending = pending === entry.plugin_id;
                    return (
                      <tr key={entry.plugin_id}>
                        <td style={{ color: 'var(--ink)', fontWeight: 500 }}>
                          {entry.homepage ? (
                            <a href={entry.homepage} target="_blank" rel="noreferrer"
                               className="inline-flex items-center gap-1" style={{ color: 'inherit' }}>
                              {entry.name} <ExternalLink className="h-3 w-3 text-ink-3" />
                            </a>
                          ) : entry.name}
                        </td>
                        <td className="text-ink-2">{entry.description}</td>
                        <td className="num text-ink-3">{entry.ref}</td>
                        <td className="text-ink-3">{entry.maintainer || '—'}</td>
                        <td>
                          <div className="flex justify-end">
                            {status?.installed ? (
                              <span className="chip tone-6">
                                <CheckCircle2 className="h-3.5 w-3.5" /> Installed
                              </span>
                            ) : (
                              <button
                                onClick={() => handleInstall(entry)}
                                disabled={isPending}
                                className="btn-accent"
                              >
                                {isPending
                                  ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                  : <Download className="h-3.5 w-3.5" />}
                                Install
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <div className="clay flex flex-col gap-3 p-3.5">
        <div className="flex items-center gap-2">
          <Circle className="h-4 w-4 text-ink-3" />
          <p className="section-title m-0">Installed on This Workstation</p>
        </div>
        <div className="well overflow-hidden" style={{ borderRadius: 12 }}>
          {isLoading ? (
            <p className="py-10 text-center text-[13px] text-ink-3">Loading status…</p>
          ) : statuses.filter(s => s.installed).length === 0 ? (
            <p className="py-10 text-center text-[13px] text-ink-3">
              Nothing installed yet. Install a plugin from the catalog above.
            </p>
          ) : (
            <div className="max-h-[40vh] overflow-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Version</th>
                    <th>State</th>
                    <th>Restarts</th>
                    <th>Last Error</th>
                    <th style={{ textAlign: 'right' }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {statuses.filter(s => s.installed).map(status => {
                    const isPending = pending === status.plugin_id;
                    return (
                      <tr key={status.plugin_id}>
                        <td style={{ color: 'var(--ink)', fontWeight: 500 }}>
                          {status.name || status.plugin_id}
                        </td>
                        <td className="num text-ink-3">{status.version || '—'}</td>
                        <td>
                          {!status.enabled ? (
                            <span className="chip" style={{ color: 'var(--ink-3)', background: 'var(--well-grid)' }}>
                              Disabled
                            </span>
                          ) : status.running ? (
                            <span className="chip tone-6">
                              <CheckCircle2 className="h-3.5 w-3.5" /> Running{status.pid ? ` (pid ${status.pid})` : ''}
                            </span>
                          ) : (
                            <span className="chip tone-4">
                              <XCircle className="h-3.5 w-3.5" /> Stopped
                            </span>
                          )}
                        </td>
                        <td className="num">{status.restarts}</td>
                        <td className="text-ink-3" style={{ maxWidth: 320 }}>
                          {status.last_error
                            ? <span title={status.last_error} className="line-clamp-1" style={{ color: 'var(--s2)' }}>{status.last_error}</span>
                            : '—'}
                        </td>
                        <td>
                          <div className="flex justify-end gap-1.5">
                            {status.running ? (
                              <button
                                onClick={() => handleStop(status)}
                                disabled={isPending}
                                aria-label={`Stop ${status.name || status.plugin_id}`}
                                title="Stop"
                                className="btn-ghost"
                              >
                                {isPending
                                  ? <Loader2 className="h-4 w-4 animate-spin" />
                                  : <Square className="h-4 w-4" />}
                              </button>
                            ) : (
                              <button
                                onClick={() => handleStart(status)}
                                disabled={isPending}
                                aria-label={`Start ${status.name || status.plugin_id}`}
                                title="Start"
                                className="btn-ghost"
                                style={{ color: 'var(--s6)' }}
                              >
                                {isPending
                                  ? <Loader2 className="h-4 w-4 animate-spin" />
                                  : <Play className="h-4 w-4" />}
                              </button>
                            )}
                            <button
                              onClick={() => handleUninstall(status)}
                              disabled={isPending}
                              aria-label={`Uninstall ${status.name || status.plugin_id}`}
                              title="Uninstall"
                              className="btn-ghost"
                              style={{ color: 'var(--s2)' }}
                            >
                              {isPending
                                ? <Loader2 className="h-4 w-4 animate-spin" />
                                : <Trash2 className="h-4 w-4" />}
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <p className="m-0 text-[11.5px] text-ink-3">
          A plugin's manifest (<span className="mono">plugin.json</span>) is validated before it is ever started --
          see <span className="mono">plugins/PLUGIN_DEVELOPER_GUIDE.md</span> for the "Flawless Setup" standard
          every catalog entry is held to.
        </p>
      </div>
    </div>
  );
};
