/**
 * Colours come from CSS variables in src/index.css, so one class works
 * in both dark and light mode and the palette can change in one place.
 *
 * @type {import('tailwindcss').Config}
 */
const token = (name) => `var(--${name})`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  // Built as `chip-${tone}`, which the content scan cannot see.
  safelist: ["chip-run", "chip-ok", "chip-ask", "chip-bad", "chip-brand", "chip-mute"],
  theme: {
    extend: {
      colors: {
        bg: token("bg"),
        side: token("side"),
        panel: token("panel"),
        raised: token("raised"),
        sunken: token("sunken"),
        line: token("line"),
        line2: token("line2"),
        ink: token("text"),
        muted: token("muted"),
        dim: token("dim"),
        accent: {
          DEFAULT: token("accent"),
          2: token("accent2"),
          on: token("on-accent"),
          text: token("accent-text"),
          soft: token("accent-soft"),
          line: token("accent-line"),
        },
        spark: token("spark"),
        run: { DEFAULT: token("run"), soft: token("run-soft"), text: token("run-text") },
        ok: { DEFAULT: token("ok"), soft: token("ok-soft"), text: token("ok-text"), on: token("on-ok") },
        ask: { DEFAULT: token("ask"), soft: token("ask-soft"), text: token("ask-text"), on: token("on-ask") },
        bad: { DEFAULT: token("bad"), soft: token("bad-soft"), text: token("bad-text"), on: token("on-bad") },
      },
      fontFamily: {
        display: ["Geist", "ui-sans-serif", "system-ui", "'Segoe UI'", "sans-serif"],
        sans: ["Geist", "ui-sans-serif", "system-ui", "'Segoe UI'", "sans-serif"],
        mono: ["'Geist Mono'", "ui-monospace", "Menlo", "monospace"],
      },
      boxShadow: {
        lift: token("shadow"),
      },
    },
  },
  plugins: [],
};
