// Grafica de linea deslizante para metricas en vivo.
//
// Mantiene una ventana fija de puntos: al llegar uno nuevo, sale el mas
// antiguo. Sin este limite el array crece sin fin y una pestana abierta toda
// la noche acaba con decenas de miles de puntos que Chart.js redibuja entero.

import { COLORS, alpha, timeAxis, valueAxis } from './base.js';

export class RealtimeChart {
  constructor(canvas, { series, maxPoints = 90, format = (v) => v, axis = {} }) {
    this.maxPoints = maxPoints;
    this.format = format;

    this.chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels: [],
        datasets: series.map((definition, index) => {
          const color = definition.color ?? COLORS.series[index % COLORS.series.length];
          return {
            label: definition.label,
            data: [],
            borderColor: color,
            backgroundColor: definition.fill === false ? 'transparent' : alpha(color, 0.14),
            fill: definition.fill === false ? false : 'origin',
            spanGaps: true,
          };
        }),
      },
      options: {
        // Una sola serie no necesita leyenda: el titulo de la tarjeta la nombra.
        plugins: {
          legend: { display: series.length > 1, position: 'bottom' },
          tooltip: {
            // Crosshair: al pasar por cualquier punto del eje X se muestran
            // todas las series de ese instante, no solo la linea tocada.
            mode: 'index',
            intersect: false,
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${this.format(ctx.parsed.y)}`,
            },
          },
        },
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: timeAxis,
          y: valueAxis({ format: (value) => this.format(value), ...axis }),
        },
      },
    });
  }

  push(label, values) {
    const { data } = this.chart;
    data.labels.push(label);
    values.forEach((value, index) => data.datasets[index]?.data.push(value));
    if (data.labels.length > this.maxPoints) {
      data.labels.shift();
      data.datasets.forEach((dataset) => dataset.data.shift());
    }
    // 'none' salta el recalculo de animacion: es la diferencia entre un
    // repintado barato y uno que quema CPU en el cliente.
    this.chart.update('none');
  }

  replace(labels, seriesData) {
    const { data } = this.chart;
    data.labels = labels;
    seriesData.forEach((values, index) => {
      if (data.datasets[index]) data.datasets[index].data = values;
    });
    this.chart.update('none');
  }

  get pointCount() {
    return this.chart.data.labels.length;
  }

  destroy() {
    this.chart.destroy();
  }
}
