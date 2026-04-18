import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        'bg-0': 'rgb(var(--bg-0) / <alpha-value>)',
        'bg-1': 'rgb(var(--bg-1) / <alpha-value>)',
        'bg-2': 'rgb(var(--bg-2) / <alpha-value>)',
        'bg-3': 'rgb(var(--bg-3) / <alpha-value>)',
        'line-1': 'rgb(var(--line-1) / <alpha-value>)',
        'line-2': 'rgb(var(--line-2) / <alpha-value>)',
        'ink-0': 'rgb(var(--ink-0) / <alpha-value>)',
        'ink-1': 'rgb(var(--ink-1) / <alpha-value>)',
        'ink-2': 'rgb(var(--ink-2) / <alpha-value>)',
        'ink-3': 'rgb(var(--ink-3) / <alpha-value>)',
        bully: 'oklch(var(--bully) / <alpha-value>)',
        alpha: 'oklch(var(--alpha) / <alpha-value>)',
        edge: 'oklch(var(--edge) / <alpha-value>)',
        combo: 'oklch(var(--combo) / <alpha-value>)',
        win: 'oklch(var(--win) / <alpha-value>)',
        lose: 'oklch(var(--lose) / <alpha-value>)',
        warn: 'oklch(var(--warn) / <alpha-value>)',
      },
      fontFamily: {
        sans: ['IBM Plex Sans', 'system-ui', 'sans-serif'],
        mono: ['IBM Plex Mono', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        panel: '0 22px 80px rgba(0, 0, 0, 0.38)',
      },
    },
  },
  plugins: [],
} satisfies Config
