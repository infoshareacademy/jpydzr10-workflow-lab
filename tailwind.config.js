/**
 * Tailwind CSS v3 — build config dla Planera Maszyn.
 *
 * Sources (`content`) — Tailwind skanuje te ścieżki w poszukiwaniu klas
 * używanych w templatkach Django (i JS), żeby generować tylko te utility,
 * które są realnie używane (pełna lista wszystkich klas Tailwind to
 * ~3.5 MB — JIT scanning daje ~30-50 KB).
 *
 * `safelist` — klasy używane DYNAMICZNIE (np. budowane stringiem w Django
 * w {% if %} branchach lub w JS template literals) muszą być wymienione
 * jawnie, bo skaner statyczny ich nie wykryje.
 *
 * `darkMode: "class"` — dark mode po `<html class="dark">` (toggle przez
 * themeToggle() Alpine component), nie po `prefers-color-scheme`. Zgodne
 * z aktualnym wcześniejszym configiem inline w base.html.
 *
 * Brand colors — match istniejący config inline (jednolite z Tailwind
 * Play CDN scope wcześniej, bez wizualnej zmiany).
 */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./*/templates/**/*.html",
    "./static/js/**/*.js",
    "./*/forms.py",
    "./*/widgets.py",
  ],
  safelist: [
    // Status kolory używane w {% if status == ... %} branchach (Django nie
    // exportuje pełnego stringa, skaner widzi tylko fragment).
    "bg-emerald-50", "border-emerald-200", "text-emerald-800",
    "dark:bg-emerald-900/20", "dark:border-emerald-800", "dark:text-emerald-200",
    "bg-rose-50", "border-rose-200", "text-rose-800",
    "dark:bg-rose-900/20", "dark:border-rose-800", "dark:text-rose-200",
    "bg-amber-50", "border-amber-200", "text-amber-800",
    "dark:bg-amber-900/20", "dark:border-amber-800", "dark:text-amber-200",
    "bg-brand-50", "border-brand-200", "text-brand-800",
    "dark:bg-brand-900/20", "dark:border-brand-800", "dark:text-brand-200",
    // Kropki statusu przegladu — budowane w machines_tags.inspection_dot
    // (templatetags/*.py nie jest skanowany; klasa wstawiana dynamicznie).
    "bg-emerald-500", "bg-amber-500", "bg-rose-500", "bg-slate-400", "dark:bg-slate-500",
  ],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      colors: {
        // Brand = niebieski (match UNFOLD COLORS.primary). Wartości
        // 1:1 z poprzednim configiem inline w base.html.
        brand: {
          50: "#eff6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          300: "#93c5fd",
          400: "#60a5fa",
          500: "#3b82f6",
          600: "#2563eb",
          700: "#1d4ed8",
          800: "#1e40af",
          900: "#1e3a8a",
          950: "#172554",
        },
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0", transform: "translateY(-4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-in": "fade-in 200ms cubic-bezier(0.4, 0, 0.2, 1)",
      },
    },
  },
  plugins: [],
};
