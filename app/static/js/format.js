// Formateo compartido. Todo lo numerico pasa por aqui para que las unidades
// sean coherentes entre tarjetas, tablas, ejes y tooltips.

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];

export function bytes(value, decimals = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  if (value < 1) return '0 B';
  const exp = Math.min(Math.floor(Math.log(value) / Math.log(1024)), UNITS.length - 1);
  const scaled = value / 1024 ** exp;
  // Los bytes sueltos no llevan decimales: "512 B", no "512.0 B".
  return `${scaled.toFixed(exp === 0 ? 0 : decimals)} ${UNITS[exp]}`;
}

export function bps(value) {
  if (value === null || value === undefined) return '—';
  return `${bytes(value)}/s`;
}

export function pct(value, decimals = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${Number(value).toFixed(decimals)}%`;
}

export function duration(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  const s = Math.max(0, Math.floor(seconds));
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${s % 60}s`;
  return `${s}s`;
}

export function clockTime(epochSeconds) {
  return new Date(epochSeconds * 1000).toLocaleTimeString('es-ES', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

export function dateTime(epochSeconds) {
  return new Date(epochSeconds * 1000).toLocaleString('es-ES', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  });
}

export function relative(epochSeconds) {
  return duration(Date.now() / 1000 - epochSeconds);
}

// Nivel de severidad a partir de un porcentaje de uso. Se usa para bordes y
// barras, siempre junto al numero: el color nunca es la unica senal.
export function usageLevel(percent, warn = 80, crit = 90) {
  if (percent === null || percent === undefined) return 'ok';
  if (percent >= crit) return 'critical';
  if (percent >= warn) return 'warning';
  return 'ok';
}

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));
}
