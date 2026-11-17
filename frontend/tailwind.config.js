/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        obsidian: {
          DEFAULT: '#080c14',
          50: '#1e293b',
          100: '#172033',
          200: '#131b2e',
          300: '#0f172a',
          400: '#0b1120',
          500: '#080c14',
          card: '#0f172a',
          panel: '#0d131f',
          surface: '#1e293b',
          border: 'rgba(51, 65, 85, 0.4)',
        },
        trade: {
          cyan: '#06b6d4',
          emerald: '#10b981',
          rose: '#f43f5e',
          amber: '#f59e0b',
          blue: '#3b82f6',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'Menlo', 'Monaco', 'Courier New', 'monospace'],
      },
      boxShadow: {
        'glow-cyan': '0 0 15px -3px rgba(6, 182, 212, 0.3)',
        'glow-emerald': '0 0 15px -3px rgba(16, 185, 129, 0.3)',
        'glow-rose': '0 0 15px -3px rgba(244, 63, 94, 0.3)',
      },
    },
  },
  plugins: [],
};
