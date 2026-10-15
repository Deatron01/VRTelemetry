// src/frontend/VRTelemetry/src/App.tsx

import React, { useEffect, useState } from 'react';
import { AppShell } from './components/layout/AppShell';
import { Overview } from './pages/Overview';
import { Patients } from './pages/Patients';
import { EyeTracking } from './pages/EyeTracking';
import { Physiology } from './pages/Physiology';
import { RawDataExplorer } from './pages/RawDataExplorer';
import { DataQuality } from './pages/DataQuality';
import { Metadata } from './pages/Metadata';
import { Export } from './pages/Export';
import { Plugins } from './pages/Plugins';
import { SpatialViewer } from './components/visualizations/SpatialViewer';
import { SessionVideoPanel } from './components/visualizations/SessionVideoPanel';
import { SessionExplorer } from './pages/SessionExplorer';
import { ResearchInsights } from './pages/ResearchInsights';
import { NewSession } from './pages/NewSession';
import { Login } from './pages/Login';
import { Activation } from './pages/Activation';


interface AuthedUser {
  email: string;
  display_name: string;
}

type LicenseState = 'checking' | 'active' | 'inactive';

/** Pre-shell states (auth check, license check) get the same canvas treatment
    as the app proper, so startup doesn't flash an unstyled white page. */
const BootScreen: React.FC<{ message: string }> = ({ message }) => (
  <div className="flex min-h-screen flex-col items-center justify-center gap-4">
    <div className="clay flex h-14 w-14 items-center justify-center" style={{ color: 'var(--s1)' }}>
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.1"
           strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2" />
      </svg>
    </div>
    <p className="m-0 text-[13px] text-ink-2" role="status">{message}…</p>
  </div>
);

function App() {
  const [route, setRoute] = useState('overview');
  const [authChecked, setAuthChecked] = useState(false);
  const [user, setUser] = useState<AuthedUser | null>(null);
  const [licenseState, setLicenseState] = useState<LicenseState>('checking');

  const checkAuth = () => {
    fetch('http://localhost:8000/api/auth/session')
      .then(r => r.json())
      .then(data => {
        if (data.authenticated) {
          setUser({ email: data.email, display_name: data.display_name });
        } else {
          setUser(null);
        }
      })
      .catch(() => setUser(null))
      .finally(() => setAuthChecked(true));
  };

  const checkLicense = () => {
    fetch('http://localhost:8000/api/license/status')
      .then(r => r.json())
      .then(data => {
        const isUsable = data.activated && (data.status === 'active');
        setLicenseState(isUsable ? 'active' : 'inactive');
      })
      .catch(() => setLicenseState('inactive'));
  };

  useEffect(() => {
    checkAuth();
  }, []);

  useEffect(() => {
    if (user) checkLicense();
  }, [user]);

  const handleLogout = async () => {
    try {
      await fetch('http://localhost:8000/api/auth/logout', { method: 'POST' });
    } finally {
      setUser(null);
      setLicenseState('checking');
    }
  };

  if (!authChecked) {
    return <BootScreen message="Loading workspace" />;
  }

  if (!user) {
    return <Login onAuthenticated={(session) => setUser(session)} />;
  }

  if (licenseState === 'checking') {
    return <BootScreen message="Verifying license" />;
  }

  if (licenseState === 'inactive') {
    return <Activation onActivated={() => setLicenseState('active')} />;
  }

  const renderContent = () => {
    switch (route) {
      case 'overview': return <Overview onNavigate={setRoute} />;
      case 'patients': return <Patients />;
      case 'record': return <NewSession />;
      case 'explorer': return <SessionExplorer onNavigate={setRoute} />;
      case 'eye': return <EyeTracking />;
      case 'physiology': return <Physiology />;
      case 'quality': return <DataQuality />;
      case 'metadata': return <Metadata />;
      case 'raw': return <RawDataExplorer />;
      case 'insights': return <ResearchInsights />;
      case 'export': return <Export />;
      case 'plugins': return <Plugins />;
      case 'spatial': return (
        <div className="mx-auto flex h-full max-w-[1600px] flex-col gap-4">
          <div>
            <h1 className="page-title">Spatial &amp; Gaze Analysis</h1>
            <p className="page-sub">
              Reconstructed head, hand and gaze geometry — alongside the session's recorded screen
              capture, when one exists — scrubbed together by the transport bar below.
            </p>
          </div>
          <div className="grid min-h-0 flex-1 grid-cols-1 gap-3.5 lg:grid-cols-5">
            <div className="clay min-h-[320px] overflow-hidden p-1.5 lg:col-span-2">
              <SessionVideoPanel />
            </div>
            <div className="clay min-h-[320px] overflow-hidden p-1.5 lg:col-span-3">
              <div className="h-full w-full overflow-hidden rounded-[12px]"><SpatialViewer /></div>
            </div>
          </div>
        </div>
      );
      default: return <Overview onNavigate={setRoute} />;
    }
  };

  return (
    <AppShell currentRoute={route} onRouteChange={setRoute} user={user} onLogout={handleLogout}>
      {renderContent()}
    </AppShell>
  );
}

export default App;
