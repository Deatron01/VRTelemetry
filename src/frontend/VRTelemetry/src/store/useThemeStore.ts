import { create } from 'zustand';

type ThemePreference = 'light' | 'dark' | 'system';

interface ThemeState {
  preference: ThemePreference;
  isDark: boolean;
  setPreference: (pref: ThemePreference) => void;
  toggle: () => void;
}

const STORAGE_KEY = 'vrtelemetry-theme-preference';

function systemPrefersDark(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function resolveIsDark(pref: ThemePreference): boolean {
  return pref === 'dark' || (pref === 'system' && systemPrefersDark());
}

function applyToDocument(isDark: boolean) {
  if (typeof document === 'undefined') return;
  // Two switches for one state, deliberately: Tailwind's darkMode:'class' reads
  // `.dark`, while the Vitrum token blocks in index.css also accept
  // [data-theme="dark"] so markup lifted straight from the design canvas themes
  // correctly without being rewritten.
  document.documentElement.classList.toggle('dark', isDark);
  document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
}

function loadStoredPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored;
  } catch {
    // localStorage unavailable (privacy mode, etc.) — fall back to system preference.
  }
  return 'system';
}

const initialPreference = loadStoredPreference();
const initialIsDark = resolveIsDark(initialPreference);
applyToDocument(initialIsDark);

export const useThemeStore = create<ThemeState>((set, get) => ({
  preference: initialPreference,
  isDark: initialIsDark,
  setPreference: (pref) => {
    const isDark = resolveIsDark(pref);
    applyToDocument(isDark);
    try { localStorage.setItem(STORAGE_KEY, pref); } catch { /* ignore */ }
    set({ preference: pref, isDark });
  },
  toggle: () => {
    const next = get().isDark ? 'light' : 'dark';
    get().setPreference(next);
  },
}));

// Keep in sync with OS-level changes while preference is 'system'.
if (typeof window !== 'undefined' && window.matchMedia) {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    const { preference, setPreference } = useThemeStore.getState();
    if (preference === 'system') setPreference('system');
  });
}
