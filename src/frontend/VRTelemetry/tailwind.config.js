/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // --- Vitrum design-system tokens (see src/index.css) ------------------
        // Plain `var()` aliases: these carry oklch()/rgba() values, so Tailwind's
        // <alpha-value> substitution can't apply. Use the CSS component classes
        // (.clay, .glass, .well, .chip, .tone-N) for anything needing opacity.
        ink: {
          DEFAULT: 'var(--ink)',
          2: 'var(--ink-2)',
          3: 'var(--ink-3)',
        },
        canvas: 'var(--canvas)',
        hair: 'var(--hair)',
        well: {
          DEFAULT: 'var(--well)',
          line: 'var(--well-line)',
          grid: 'var(--well-grid)',
        },
        s1: 'var(--s1)', 's1-soft': 'var(--s1-soft)',
        s2: 'var(--s2)', 's2-soft': 'var(--s2-soft)',
        s3: 'var(--s3)', 's3-soft': 'var(--s3-soft)',
        s4: 'var(--s4)', 's4-soft': 'var(--s4-soft)',
        s5: 'var(--s5)', 's5-soft': 'var(--s5-soft)',
        s6: 'var(--s6)', 's6-soft': 'var(--s6-soft)',

        // --- Legacy `research.*` aliases --------------------------------------
        // Still referenced by markup that predates the Vitrum port. The RGB-triple
        // variables are remapped onto the Vitrum palette in src/index.css, so
        // opacity modifiers (bg-research-blue/20) keep working during migration.
        research: {
          bg: 'rgb(var(--research-bg) / <alpha-value>)',
          card: 'var(--research-card)',
          border: 'var(--research-border)',
          text: 'rgb(var(--research-text) / <alpha-value>)',
          muted: 'rgb(var(--research-muted) / <alpha-value>)',
          blue: 'rgb(var(--research-blue) / <alpha-value>)',
          green: 'rgb(var(--research-green) / <alpha-value>)',
          graphite: 'rgb(var(--research-graphite) / <alpha-value>)',
        },
      },
      boxShadow: {
        clay: 'var(--clay-shadow), var(--clay-lip)',
        'clay-press': 'var(--clay-press)',
        glass: 'var(--glass-shadow)',
        act: 'var(--act-glow)',
        'act-lg': 'var(--act-glow-lg)',
      },
      backgroundImage: {
        clay: 'linear-gradient(145deg, var(--clay-a), var(--clay-b))',
        'clay-inset': 'linear-gradient(145deg, var(--clay-b), var(--clay-a))',
        act: 'linear-gradient(145deg, var(--act-a), var(--act-b))',
      },
      borderRadius: {
        clay: '16px',
      },
      fontFamily: {
        sans: ['IBM Plex Sans', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['IBM Plex Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
}
