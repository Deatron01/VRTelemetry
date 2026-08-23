import React, { useState } from 'react';
import { AppShell } from './components/layout/AppShell';
import { Overview } from './pages/Overview';
import { EyeTracking } from './pages/EyeTracking';
import { Physiology } from './pages/Physiology';
import { RawDataExplorer } from './pages/RawDataExplorer';
import { DataQuality } from './pages/DataQuality';
import { Metadata } from './pages/Metadata';
import { Export } from './pages/Export';
import { SpatialViewer } from './components/visualizations/SpatialViewer';
import { SessionExplorer } from './pages/SessionExplorer';
import { NewSession } from './pages/NewSession';

function App() {
  const [route, setRoute] = useState('overview');

  const renderContent = () => {
    switch (route) {
      case 'overview': return <Overview />;
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
    <AppShell currentRoute={route} onRouteChange={setRoute}>
      {renderContent()}
    </AppShell>
  );
}

export default App;