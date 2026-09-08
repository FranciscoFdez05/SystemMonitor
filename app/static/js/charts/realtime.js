// Gráfica de línea deslizante para métricas en vivo.
//
// Mantiene una ventana fija de puntos: al llegar uno nuevo, sale el más
// antiguo. Sin este límite el array crece sin fin y una pestaña abierta toda
// la noche acaba con decenas de miles de puntos que Chart.js redibuja entero.

import { COLORS, alpha, timeAxis, valueAxis } from './base.js';

// Escalones "redondos" para el techo del eje. Que el máximo caiga siempre en
// uno de estos evita que el eje muestre 137.4 KB/s un segundo y 152.9 KB/s al
// siguiente: la rejilla se queda quieta aunque los datos se muevan.
const ESCALONES = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];

function techoRedondo(valor) {
  if (!(valor > 0)) return 1;
  const exponente = Math.floor(Math.log10(valor));
  const base = 10 ** exponente;
  for (const escalon of ESCALONES) {
    const candidato = escalon * base;
    if (candidato >= valor) return candidato;
  }
  return 10 * base;
}

export class RealtimeChart {
  /**
   * @param {object} opciones
   * @param {object} [opciones.stableAxis] Techo del eje Y calculado a partir de
   *   los datos, pero estabilizado. Sin esto, un eje automático se reescala en
   *   cada tick y la línea parece saltar aunque los valores apenas cambien.
   *   - `floor`: techo mínimo, para que una gráfica en reposo no amplíe el ruido.
   *   - `decayTicks`: cuántas actualizaciones seguidas debe caber el dato en un
   *     techo más bajo antes de bajarlo. Subir es inmediato (un pico no se puede
   *     salir del cuadro); bajar es lento, que es lo que evita el vaivén.
   */
  constructor(canvas, { series, maxPoints = 90, format = (v) => v, axis = {},
                        stableAxis = null }) {
    this.maxPoints = maxPoints;
    this.format = format;
    this.stableAxis = stableAxis;
    this.techoActual = stableAxis ? stableAxis.floor ?? 1 : null;
    this.ticksPorDebajo = 0;

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
            backgroundColor: definition.fill === false ? 'transparent' : alpha(color, 0.10),
            fill: definition.fill === false ? false : 'origin',
            spanGaps: true,
          };
        }),
      },
      options: {
        // Una sola serie no necesita leyenda: el título de la tarjeta la nombra.
        plugins: {
          legend: { display: series.length > 1, position: 'bottom' },
          tooltip: {
            // Crosshair: al pasar por cualquier punto del eje X se muestran
            // todas las series de ese instante, no solo la línea tocada.
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

    if (this.stableAxis) this.chart.options.scales.y.max = this.techoActual;
  }

  /** Ajusta el techo del eje, subiendo al momento y bajando con retardo. */
  _ajustarTecho() {
    if (!this.stableAxis) return;
    let pico = 0;
    for (const dataset of this.chart.data.datasets) {
      for (const valor of dataset.data) {
        if (typeof valor === 'number' && valor > pico) pico = valor;
      }
    }
    // Un 15 % de aire por encima del pico: si la línea toca el borde superior
    // parece cortada y no se distingue un máximo real de uno recortado.
    const deseado = Math.max(techoRedondo(pico * 1.15), this.stableAxis.floor ?? 1);

    if (deseado > this.techoActual) {
      this.techoActual = deseado;
      this.ticksPorDebajo = 0;
    } else if (deseado < this.techoActual) {
      this.ticksPorDebajo += 1;
      if (this.ticksPorDebajo >= (this.stableAxis.decayTicks ?? 20)) {
        this.techoActual = deseado;
        this.ticksPorDebajo = 0;
      }
    } else {
      this.ticksPorDebajo = 0;
    }
    this.chart.options.scales.y.max = this.techoActual;
  }

  push(label, values) {
    const { data } = this.chart;
    data.labels.push(label);
    values.forEach((value, index) => data.datasets[index]?.data.push(value));
    if (data.labels.length > this.maxPoints) {
      data.labels.shift();
      data.datasets.forEach((dataset) => dataset.data.shift());
    }
    this._ajustarTecho();
    // 'none' salta el recálculo de animación: es la diferencia entre un
    // repintado barato y uno que quema CPU en el cliente.
    this.chart.update('none');
  }

  replace(labels, seriesData) {
    const { data } = this.chart;
    data.labels = labels;
    seriesData.forEach((values, index) => {
      if (data.datasets[index]) data.datasets[index].data = values;
    });
    // En un histórico completo el techo se fija de una vez: no hay vaivén que
    // suavizar porque los datos no llegan poco a poco.
    if (this.stableAxis) {
      this.ticksPorDebajo = this.stableAxis.decayTicks ?? 20;
      this._ajustarTecho();
    }
    this.chart.update('none');
  }

  get pointCount() {
    return this.chart.data.labels.length;
  }

  destroy() {
    this.chart.destroy();
  }
}
