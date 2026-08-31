// src/frontend/VRTelemetry/src/services/chartTheme.ts
//
// Recharts takes colours as plain strings, so it can't read the design system's
// CSS variables the way the rest of the UI does. This hook resolves them once
// per theme change and hands back concrete values — which is what keeps the
// charts legible in dark mode instead of drawing slate-200 gridlines on near-black.

import { useMemo } from 'react';
import { useThemeStore } from '../store/useThemeStore';

export interface ChartTokens {
  grid: string;
  axis: string;
  ink: string;
  hair: string;
  surface: string;
  s1: string; s2: string; s3: string; s4: string; s5: string; s6: string;
  tooltip: React.CSSProperties;
  tooltipLabel: React.CSSProperties;
}

const FALLBACK: Record<string, string> = {
  '--well-grid': 'rgba(20,29,48,.055)',
  '--ink-3': '#5c6880',
  '--ink': '#0f1729',
  '--hair': 'rgba(20,29,48,.10)',
  '--clay-a': '#fcfdff',
  '--s1': '#2f57b8', '--s2': '#b4551f', '--s3': '#237a8c',
  '--s4': '#94701f', '--s5': '#7b3fb0', '--s6': '#227a54',
};

export function useChartTokens(): ChartTokens {
  // isDark isn't used in the computation — it's the dependency that makes the
  // memo re-resolve after the class on <html> flips.
  const isDark = useThemeStore(s => s.isDark);

  return useMemo(() => {
    const read = (name: string): string => {
      if (typeof window === 'undefined' || typeof document === 'undefined') return FALLBACK[name];
      const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      return value || FALLBACK[name];
    };

    const surface = read('--clay-a');
    const hair = read('--hair');
    const ink = read('--ink');

    return {
      grid: read('--well-grid'),
      axis: read('--ink-3'),
      ink,
      hair,
      surface,
      s1: read('--s1'), s2: read('--s2'), s3: read('--s3'),
      s4: read('--s4'), s5: read('--s5'), s6: read('--s6'),
      tooltip: {
        borderRadius: 10,
        border: `1px solid ${hair}`,
        background: surface,
        color: ink,
        boxShadow: '0 10px 30px -14px rgba(0,0,0,.45)',
        fontSize: 12,
      },
      tooltipLabel: { color: read('--ink-3'), fontSize: 11 },
    };
  }, [isDark]);
}
