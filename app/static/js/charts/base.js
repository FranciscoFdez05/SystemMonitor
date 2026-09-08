// Tokens de color y ajustes comunes de Chart.js.
//
// Los colores se leen de las variables CSS para que exista una sola definicion
// de la paleta: si cambia el tema, cambian las graficas sin tocar JS.

const css = getComputedStyle(document.documentElement);
const token = (name, fallback) => (css.getPropertyValue(name).trim() || fallback);

export const COLORS = {
  surface: token('--surface', '#1a1a19'),
  text: token('--text', '#ffffff'),
  text2: token('--text-2', '#c3c2b7'),
  muted: token('--muted', '#898781'),
  grid: token('--grid', '#2c2c2a'),
  baseline: token('--baseline', '#383835'),
  series: [
    token('--series-1', '#3987e5'),
    token('--series-2', '#d95926'),
    token('--series-3', '#199e70'),
    token('--series-4', '#c98500'),
    token('--series-5', '#d55181'),
  ],
  status: {
    ok: token('--series-1', '#3987e5'),
    good: token('--good', '#0ca30c'),
    warning: token('--warning', '#fab219'),
    serious: token('--serious', '#ec835a'),
    critical: token('--critical', '#d03b3b'),
  },
};

export function statusColor(level) {
  return COLORS.status[level] ?? COLORS.status.ok;
}

// Convierte un hex en rgba para los rellenos por debajo de la linea.
export function alpha(hex, value) {
  const clean = hex.replace('#', '');
  const int = parseInt(clean.length === 3 ? clean.replace(/./g, '$&$&') : clean, 16);
  return `rgba(${(int >> 16) & 255}, ${(int >> 8) & 255}, ${int & 255}, ${value})`;
}

export function applyDefaults() {
  const { defaults } = Chart;
  defaults.font.family = css.getPropertyValue('--font').trim()
    || 'system-ui, -apple-system, "Segoe UI", sans-serif';
  defaults.font.size = 11;
  defaults.color = COLORS.muted;
  // Sin animacion: en una Pi (y en el navegador que la mira) animar cada
  // actualizacion de 2 s cuesta mas que dibujar el dato.
  defaults.animation = false;
  defaults.animations.colors = false;
  defaults.transitions.active.animation.duration = 0;
  defaults.maintainAspectRatio = false;
  defaults.responsive = true;
  defaults.elements.line.borderWidth = 2;
  defaults.elements.line.tension = 0.25;
  defaults.elements.point.radius = 0;
  defaults.elements.point.hitRadius = 12;   // objetivo de raton mayor que la marca
  defaults.elements.point.hoverRadius = 4;

  defaults.plugins.legend.labels.boxWidth = 10;
  defaults.plugins.legend.labels.boxHeight = 10;
  defaults.plugins.legend.labels.usePointStyle = true;
  defaults.plugins.legend.labels.color = COLORS.text2;
  defaults.plugins.legend.labels.padding = 14;

  defaults.plugins.tooltip.backgroundColor = '#000000cc';
  defaults.plugins.tooltip.borderColor = COLORS.baseline;
  defaults.plugins.tooltip.borderWidth = 1;
  defaults.plugins.tooltip.titleColor = COLORS.text;
  defaults.plugins.tooltip.bodyColor = COLORS.text2;
  defaults.plugins.tooltip.padding = 10;
  defaults.plugins.tooltip.displayColors = true;
  defaults.plugins.tooltip.boxWidth = 8;
  defaults.plugins.tooltip.boxHeight = 8;
  defaults.plugins.tooltip.usePointStyle = true;
}

export const timeAxis = {
  grid: { display: false },
  border: { color: COLORS.baseline },
  ticks: { maxRotation: 0, autoSkipPadding: 24, color: COLORS.muted },
};

export function valueAxis({ min = null, max = null, suggestedMax = null,
                            beginAtZero = true, format = (v) => v } = {}) {
  return {
    beginAtZero,
    min,
    max,
    suggestedMax,
    grid: { color: COLORS.grid, drawTicks: false },
    border: { display: false },
    ticks: { padding: 8, color: COLORS.muted, callback: format, maxTicksLimit: 6 },
  };
}
