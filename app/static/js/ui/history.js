// Panel de historico sobre los agregados de SQLite.
//
// Las metricas se agrupan por unidad y solo se dibuja un grupo a la vez. Meter
// porcentajes y grados en la misma grafica obligaria a un segundo eje Y, y un
// grafico de doble eje se lee mal casi siempre: la posicion relativa de las
// dos lineas depende de como escales cada eje, no de los datos.

import { api } from '../api.js';
import { COLORS } from '../charts/base.js';
import { RealtimeChart } from '../charts/realtime.js';
import { bps, dateTime, duration } from '../format.js';
import { notifyError } from './toast.js';

const $ = (id) => document.getElementById(id);

const GROUPS = {
  usage: {
    axis: { max: 100 },
    format: (v) => `${Number(v).toFixed(0)}%`,
    series: [
      { key: 'cpu_pct', label: 'CPU', color: COLORS.series[0] },
      { key: 'mem_pct', label: 'RAM', color: COLORS.series[2] },
      { key: 'disk_pct', label: 'Disco raiz', color: COLORS.series[1] },
    ],
  },
  temp: {
    axis: { beginAtZero: false, min: 20, max: 90 },
    format: (v) => `${Number(v).toFixed(0)}°C`,
    series: [{ key: 'temp_c', label: 'Temperatura', color: COLORS.series[3] }],
  },
  net: {
    axis: {},
    stableAxis: { floor: 16 * 1024, decayTicks: 1 },
    format: (v) => bps(v),
    series: [
      { key: 'net_rx', label: 'Bajada', color: COLORS.series[0] },
      { key: 'net_tx', label: 'Subida', color: COLORS.series[1] },
    ],
  },
  load: {
    axis: {},
    format: (v) => Number(v).toFixed(2),
    series: [
      { key: 'load1', label: 'Carga 1 min', color: COLORS.series[0] },
      { key: 'cpu_peak', label: 'Pico CPU (%)', color: COLORS.series[4] },
    ],
  },
};

export class HistoryPanel {
  constructor() {
    this.chart = null;
    this.group = 'usage';
    this.loading = false;

    $('history-metric').addEventListener('change', (event) => {
      this.group = event.target.value;
      this.rebuild();
      this.load();
    });
    $('history-range').addEventListener('change', () => this.load());
    $('history-reload').addEventListener('click', () => this.load());
  }

  rebuild() {
    this.chart?.destroy();
    const group = GROUPS[this.group];
    this.chart = new RealtimeChart($('chart-history'), {
      series: group.series.map((s) => ({ label: s.label, color: s.color, fill: false })),
      maxPoints: Number.MAX_SAFE_INTEGER,
      format: group.format,
      axis: group.axis,
      stableAxis: group.stableAxis ?? null,
    });
  }

  async load() {
    if (this.loading) return;
    this.loading = true;
    const minutes = Number($('history-range').value);
    $('history-info').textContent = 'Cargando…';
    try {
      const data = await api.get(`/api/metrics/history?minutes=${minutes}&max_points=600`);
      if (!this.chart) this.rebuild();

      const group = GROUPS[this.group];
      const labels = data.series.map((row) => dateTime(row.ts));
      const values = group.series.map((s) => data.series.map((row) => row[s.key]));
      this.chart.replace(labels, values);

      $('history-info').textContent = data.points
        ? `${data.points} puntos · un punto cada ${duration(data.bucket_seconds)} · `
          + `desde ${dateTime(data.series[0].ts)}`
        : 'Todavia no hay historico. La primera muestra se guarda al minuto de arrancar.';
    } catch (error) {
      $('history-info').textContent = '';
      notifyError(`No se pudo cargar el historico: ${error.message}`);
    } finally {
      this.loading = false;
    }
  }
}
