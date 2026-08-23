/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        research: {
          bg: '#f8fafc',
          card: 'rgba(255, 255, 255, 0.7)',
          border: 'rgba(0, 0, 0, 0.06)',
          text: '#1e293b',
          muted: '#64748b',
          blue: '#3b82f6',
          green: '#10b981',
          graphite: '#334155',
        }
      },
      boxShadow: {
        'glass': '0 4px 24px -4px rgba(0, 0, 0, 0.05)',
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      }
    },
  },
  plugins: [],
}