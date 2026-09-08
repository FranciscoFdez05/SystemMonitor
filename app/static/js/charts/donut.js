// Donut de dos segmentos (usado / libre) con cifra central.
//
// El donut solo se usa para parte-de-un-todo con pocos segmentos, que es
// exactamente el caso de RAM y de cada particion. La cifra central es la
// etiqueta directa: no hace falta pasar el raton para leer el valor.

import { COLORS, statusColor } from './base.js';

const centerText = {
  id: 'centerText',
  afterDraw(chart, args, options) {
    const { ctx, chartArea } = chart;
    if (!chartArea || !options?.text) return;
    const x = (chartArea.left + chartArea.right) / 2;
    const y = (chartArea.top + chartArea.bottom) / 2;
    ctx.save();
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = COLORS.text;
    ctx.font = `600 ${options.size ?? 22}px ${Chart.defaults.font.family}`;
    ctx.fillText(options.text, x, y - 8);
    if (options.sub) {
      ctx.fillStyle = COLORS.muted;
      ctx.font = `400 11px ${Chart.defaults.font.family}`;
      ctx.fillText(options.sub, x, y + 12);
    }
    ctx.restore();
  },
};

export class DonutChart {
  constructor(canvas, { labels = ['Usado', 'Libre'] } = {}) {
    this.chart = new Chart(canvas, {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{
          data: [0, 100],
          backgroundColor: [COLORS.series[0], COLORS.grid],
          // Separacion de 2px del color de la superficie entre segmentos, para
          // que no se lean como una sola masa continua.
          borderColor: COLORS.surface,
          borderWidth: 2,
          hoverOffset: 4,
        }],
      },
      options: {
        cutout: '68%',
        plugins: {
          legend: { display: false },
          centerText: { text: '', sub: '' },
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.label}: ${this.formatValue(ctx.parsed, ctx.dataIndex)}`,
            },
          },
        },
      },
      plugins: [centerText],
    });
    this.formatValue = (value) => `${value}`;
  }

  update({ used, total, level = 'ok', center, sub, format }) {
    if (format) this.formatValue = format;
    const free = Math.max(0, total - used);
    const dataset = this.chart.data.datasets[0];
    dataset.data = [used, free];
    // El segmento "usado" toma el color de estado solo cuando hay problema;
    // en condiciones normales es el azul de serie.
    dataset.backgroundColor = [
      level === 'ok' ? COLORS.series[0] : statusColor(level),
      COLORS.grid,
    ];
    this.chart.options.plugins.centerText.text = center ?? '';
    this.chart.options.plugins.centerText.sub = sub ?? '';
    this.chart.update('none');
  }

  destroy() {
    this.chart.destroy();
  }
}
