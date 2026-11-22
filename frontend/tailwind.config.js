import colors from 'tailwindcss/colors';

/**
 * Light theme.
 * The components were written with dark-theme Tailwind classes. Rather than rewrite every class,
 * the palette is remapped here:
 *   - the slate (neutral) scale is inverted: slate-900 is now a light surface, slate-200 dark text
 *   - the dark tints of the accent colours (800/900/950) become light tints
 *   - the bright "on dark" accent text colours (300/400) become deeper, readable-on-white shades
 * 500-700 (solid buttons / badges) are untouched, so white text on them still works.
 */
const accents = [
  'cyan', 'emerald', 'rose', 'amber', 'purple', 'indigo', 'blue', 'red',
  'green', 'yellow', 'teal', 'violet', 'orange', 'sky',
];
const lightAccents = {};
for (const name of accents) {
  const c = colors[name];
  lightAccents[name] = {
    ...c,
    950: c[50],
    900: c[100],
    800: c[200],
    300: c[700],
    400: c[600],
    200: c[800],
    100: c[900],
  };
}

const s = colors.slate;
const invertedSlate = {
  50: s[950],
  100: s[900],
  200: s[800],
  300: s[700],
  400: s[600],
  500: s[500],
  600: s[400],
  700: s[300],
  800: s[200],
  900: s[100],
  950: s[50],
};

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ...lightAccents,
        slate: invertedSlate,
        ink: '#0f172a',
        app: '#f4f6fa',
        obsidian: {
          DEFAULT: '#f4f6fa',
          50: '#e2e8f0',
          100: '#eef1f6',
          200: '#f1f5f9',
          300: '#ffffff',
          400: '#f8fafc',
          500: '#f4f6fa',
          card: '#ffffff',
          panel: '#ffffff',
          surface: '#f1f5f9',
          border: 'rgba(148, 163, 184, 0.4)',
        },
        trade: {
          cyan: '#0891b2',
          emerald: '#059669',
          rose: '#e11d48',
          amber: '#d97706',
          blue: '#2563eb',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'Menlo', 'Monaco', 'Courier New', 'monospace'],
      },
      boxShadow: {
        'glow-cyan': '0 4px 14px -4px rgba(8, 145, 178, 0.35)',
        'glow-emerald': '0 4px 14px -4px rgba(5, 150, 105, 0.35)',
        'glow-rose': '0 4px 14px -4px rgba(225, 29, 72, 0.35)',
      },
    },
  },
  plugins: [],
};
