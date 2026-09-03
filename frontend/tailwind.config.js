/** @type {import('tailwindcss').Config} */

// Every shade below is a CSS variable defined twice in src/index.css — once for day, once
// for night — so a utility class in a component never has to know which theme is on.
const themed = (family) =>
  Object.fromEntries(
    [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950].map((shade) => [
      shade,
      `rgb(var(--${family}-${shade}) / <alpha-value>)`,
    ]),
  );

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        slate: themed('slate'),
        sky: themed('sky'),
        emerald: themed('emerald'),
        rose: themed('rose'),
        amber: themed('amber'),
      },
      // System stack only — no web fonts leave the LAN (spec §5).
      fontFamily: {
        sans: [
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
      },
    },
  },
  plugins: [],
};
