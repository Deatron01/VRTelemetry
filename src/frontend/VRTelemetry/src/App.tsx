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
import { SpatialViewer } from './components/visualizations/SpatialViewer';
import { SessionExplorer } from './pages/SessionExplorer';
import { NewSession } from './pages/NewSession';
import { Login } from './pages/Login';
import { Activation } from './pages/Activation';


interface AuthedUser {
  email: string;
  display_name: string;
}

type LicenseState = 'checking' | 'active' | 'inactive';

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
    return <div className="min-h-screen flex items-center justify-center text-research-muted">Loading...</div>;
  }

  if (!user) {
    return <Login onAuthenticated={(session) => setUser(session)} />;
  }

  if (licenseState === 'checking') {
    return <div className="min-h-screen flex items-center justify-center text-research-muted">Verifying license...</div>;
  }

  if (licenseState === 'inactive') {
    return <Activation onActivated={() => setLicenseState('active')} />;
  }

  const renderContent = () => {
    switch (route) {
      case 'overview': return <Overview />;
      case 'patients': return <Patients />;
      case 'record': return <NewSession />;
      case 'explorer': return <SessionExplorer />;
      case 'eye': return <EyeTracking />;
      case 'physiology': return <Physiology />;
      case 'quality': return <DataQuality />;
      case 'metadata': return <Metadata />;
      case 'raw': return <RawDataExplorer />;
      case 'export': return <Export />;
      case 'spatial': return (
        <div className="h-full w-full flex flex-col">
          <h1 className="text-2xl font-semibold text-research-graphite mb-4">3D Spatial & Gaze Analysis</h1>
          <div className="flex-1"><SpatialViewer /></div>
        </div>
      );
      default: return <Overview />;
    }
  };

  return (
    <AppShell currentRoute={route} onRouteChange={setRoute} user={user} onLogout={handleLogout}>
      {renderContent()}
    </AppShell>
  );
}

export default App;