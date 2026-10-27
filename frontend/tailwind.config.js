/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Industrial dark theme
        'ind-bg':       '#0f172a',   // page background — dark navy
        'ind-surface':  '#1e293b',   // card/panel background
        'ind-border':   '#334155',   // borders and dividers
        'ind-text':     '#e2e8f0',   // primary text
        'ind-muted':    '#94a3b8',   // secondary/muted text
        'ind-accent':   '#f59e0b',   // amber — primary accent
        'ind-accent2':  '#0ea5e9',   // sky blue — secondary accent
        'ind-danger':   '#ef4444',   // red — critical / Axis 1
        'ind-cluster':  '#3b82f6',   // blue — expansion clusters / Axis 2
        'ind-segment':  '#22c55e',   // green — market segments / Axis 3
        'ind-warn':     '#fb923c',   // orange — warnings
      },
      fontFamily: {
        sans: ['-apple-system', 'Segoe UI', 'system-ui', 'sans-serif'],
        mono: ['Consolas', 'Monaco', 'monospace'],
      },
    },
  },
  plugins: [],
}
