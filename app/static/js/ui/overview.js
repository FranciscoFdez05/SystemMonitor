// Panel de resumen: tarjetas de cifras, graficas en vivo y discos.

import { COLORS } from '../charts/base.js';
import { DonutChart } from '../charts/donut.js';
import { RealtimeChart } from '../charts/realtime.js';
import { bps, bytes, clockTime, duration, escapeHtml, pct, usageLevel } from '../format.js';

const $ = (id) => document.getElementById(id);

export class Overview {
  constructor({ fastInterval }) {
    this.fastInterval = fastInterval;
    // Ventana temporal de las graficas en vivo: unos 3 minutos, suficientes
    // para ver un pico sin acumular puntos indefinidamente.
    const points = Math.max(30, Math.round(180 / fastInterval));

    this.cpuChart = new RealtimeChart($('chart-cpu'), {
      series: [{ label: 'CPU', color: COLORS.series[0] }],
      maxPoints: points,
      format: (v) => `${Number(v).toFixed(0)}%`,
      axis: { max: 100 },
    });
    // Banda fija 20-90 grados en vez de empezar en cero. Una CPU en reposo vive
    // entre 40 y 60: con el eje desde 0 la linea queda aplastada en el centro y
    // una subida de 8 grados no se ve. Fija, ademas, no se reescala nunca.
    this.tempChart = new RealtimeChart($('chart-temp'), {
      series: [{ label: 'Temperatura', color: COLORS.series[3] }],
      maxPoints: points,
      format: (v) => `${Number(v).toFixed(0)}°C`,
      axis: { beginAtZero: false, min: 20, max: 90 },
    });
    this.memDonut = new DonutChart($('chart-mem'), { labels: ['Usada', 'Disponible'] });
    this.netChart = new RealtimeChart($('chart-net'), {
      series: [
        { label: 'Bajada', color: COLORS.series[0] },
        { label: 'Subida', color: COLORS.series[1] },
      ],
      maxPoints: points,
      format: (v) => bps(v),
      // El trafico va a rafagas: sin techo estable, el eje se reescalaba en
      // cada tick y la linea daba saltos aunque el trafico fuera el mismo.
      stableAxis: { floor: 64 * 1024, decayTicks: 20 },
    });

    $('cpu-window').textContent = `ventana de ${duration(points * fastInterval)}`;
    this.diskDonuts = new Map();
  }

  // ------------------------------------------------------------------- CPU
  updateCpu(data) {
    const level = usageLevel(data.percent, 80, 95);
    $('cpu-now').innerHTML = `${data.percent.toFixed(1)}<small>%</small>`;
    $('stat-cpu').dataset.level = level;
    $('cpu-detail').textContent =
      `${data.cores_logical} nucleos · ${data.freq_mhz ? `${data.freq_mhz} MHz` : 'frecuencia n/d'}`;
    const bar = $('cpu-bar');
    bar.style.width = `${Math.min(100, data.percent)}%`;
    bar.parentElement.dataset.level = level;

    $('cpu-chart-now').textContent = pct(data.percent, 1);
    $('cpu-freq').textContent = data.freq_mhz
      ? `${data.freq_mhz} MHz${data.freq_max_mhz ? ` de ${data.freq_max_mhz} MHz` : ''}`
      : '';
    this.cpuChart.push(clockTime(Date.now() / 1000), [data.percent]);

    this.renderCores(data.per_core);

    const [one, five, fifteen] = data.load;
    $('load-now').textContent = `${one.toFixed(2)}`;
    $('load-detail').textContent =
      `${five.toFixed(2)} / ${fifteen.toFixed(2)} · ${pct(data.load_percent, 0)} de ${data.cores_logical} nucleos`;
    $('stat-load').dataset.level = usageLevel(data.load_percent, 100, 200);
  }

  renderCores(cores) {
    const container = $('cores');
    if (container.children.length !== cores.length) {
      container.innerHTML = cores.map((_, index) => `
        <div class="core">
          <div class="core-head"><span>Nucleo ${index}</span><span data-core-value="${index}">—</span></div>
          <div class="bar"><span data-core-bar="${index}" style="width:0"></span></div>
        </div>`).join('');
    }
    cores.forEach((value, index) => {
      const level = usageLevel(value, 80, 95);
      container.querySelector(`[data-core-value="${index}"]`).textContent = `${value.toFixed(0)}%`;
      const bar = container.querySelector(`[data-core-bar="${index}"]`);
      bar.style.width = `${Math.min(100, value)}%`;
      bar.parentElement.dataset.level = level;
    });
  }

  // ---------------------------------------------------------------- termica
  updateThermal(data) {
    const temp = data.temp_c;
    $('temp-now').innerHTML = temp === null ? '—' : `${temp.toFixed(1)}<small>°C</small>`;
    $('temp-chart-now').textContent = temp === null ? 'sin sensor' : `${temp.toFixed(1)}°C`;
    $('stat-temp').dataset.level = data.level === 'unknown' ? 'ok' : data.level;
    $('temp-detail').textContent = temp === null
      ? 'Sensor no disponible'
      : `Aviso a ${data.warn_at}°C · critico a ${data.crit_at}°C`;
    const bar = $('temp-bar');
    bar.style.width = temp === null ? '0' : `${Math.min(100, (temp / data.crit_at) * 100)}%`;
    bar.parentElement.dataset.level = data.level === 'unknown' ? 'ok' : data.level;

    if (temp !== null) this.tempChart.push(clockTime(Date.now() / 1000), [temp]);

    // Los avisos de throttling llevan texto: en una Pi, "bajo voltaje" suele
    // ser un cargador insuficiente y conviene que se lea, no que se intuya.
    const badges = $('throttle-badges');
    const throttling = data.throttling;
    if (!throttling || !throttling.messages.length) {
      badges.innerHTML = throttling
        ? '<span class="badge-chip" data-level="good">✓ Sin throttling</span>'
        : '';
      return;
    }
    badges.innerHTML = throttling.messages.map((message) => {
      const active = !message.includes('Ha habido') && !message.includes('Se alcanzo');
      return `<span class="badge-chip" data-level="${active ? 'critical' : 'warning'}">
        ${active ? '⚠' : 'ⓘ'} ${escapeHtml(message)}</span>`;
    }).join('');
  }

  // ---------------------------------------------------------------- memoria
  updateMemory(data) {
    const level = usageLevel(data.percent, 80, 90);
    $('mem-now').innerHTML = `${data.percent.toFixed(1)}<small>%</small>`;
    $('stat-mem').dataset.level = level;
    $('mem-detail').textContent = `${bytes(data.used)} de ${bytes(data.total)}`;
    const bar = $('mem-bar');
    bar.style.width = `${data.percent}%`;
    bar.parentElement.dataset.level = level;

    $('mem-chart-now').textContent = `${bytes(data.used)} / ${bytes(data.total)}`;
    this.memDonut.update({
      used: data.used,
      total: data.total,
      level,
      center: pct(data.percent, 0),
      sub: `${bytes(data.available)} libres`,
      format: (value) => bytes(value),
    });

    $('swap-info').textContent = data.swap_total
      ? `Swap: ${bytes(data.swap_used)} de ${bytes(data.swap_total)} (${pct(data.swap_percent, 0)})`
      : 'Sin swap configurada';
  }

  // -------------------------------------------------------------------- red
  updateNetwork(data) {
    $('net-now').textContent = `↓ ${bps(data.rx_bps)}`;
    $('net-detail').textContent = `↑ ${bps(data.tx_bps)} · total ${bytes(data.rx_total + data.tx_total)}`;
    const label = clockTime(Date.now() / 1000);
    this.netChart.push(label, [data.rx_bps, data.tx_bps]);
    $('net-chart-now').textContent = `↓ ${bps(data.rx_bps)} · ↑ ${bps(data.tx_bps)}`;
    this.lastNetwork = data;
  }

  // ---------------------------------------------------------------- sistema
  updateSystem(data) {
    $('hostname').textContent = data.hostname;
    $('model').textContent = data.model;
    $('uptime').textContent = duration(data.uptime_seconds);
    $('app-uptime').textContent = duration(data.app_uptime_seconds);
    $('app-cost').textContent = `${bytes(data.app_rss)} · ${pct(data.app_cpu_percent, 1)} CPU`;
    document.title = `${data.hostname} · SystemMonitor`;
  }

  // ----------------------------------------------------------------- discos
  updateDisk(data) {
    const container = $('disks');
    const root = data.partitions.find((p) => p.mount === '/') ?? data.partitions[0];

    if (root) {
      const level = root.level === 'critical' ? 'critical'
        : root.level === 'warning' ? 'warning' : 'ok';
      $('disk-now').innerHTML = `${root.percent.toFixed(1)}<small>%</small>`;
      $('stat-disk').dataset.level = level;
      $('disk-detail').textContent = `${bytes(root.free)} libres de ${bytes(root.total)}`;
      const bar = $('disk-bar');
      bar.style.width = `${root.percent}%`;
      bar.parentElement.dataset.level = level;
    }

    $('disk-io').textContent = `E/S: lectura ${bps(data.io.read_bps)} · escritura ${bps(data.io.write_bps)}`;

    const seen = new Set();
    for (const partition of data.partitions) {
      seen.add(partition.mount);
      let entry = this.diskDonuts.get(partition.mount);
      if (!entry) {
        const card = document.createElement('div');
        card.className = 'disk-tile';
        card.innerHTML = `
          <h3></h3>
          <div class="chart-box donut"><canvas></canvas></div>
          <div class="disk-caption"></div>`;
        container.appendChild(card);
        entry = {
          card,
          donut: new DonutChart(card.querySelector('canvas'), { labels: ['Usado', 'Libre'] }),
          title: card.querySelector('h3'),
          caption: card.querySelector('.disk-caption'),
        };
        this.diskDonuts.set(partition.mount, entry);
      }
      entry.title.textContent = partition.mount;
      entry.card.dataset.level = partition.level;
      // El aviso de "queda menos del 10%" se dice con palabras ademas de con
      // el color: el borde y el anillo tinen, pero el texto es lo que lo
      // explica a quien no distinga los tonos.
      const warning = partition.level === 'critical' ? '⚠ Menos del 10 % libre'
        : partition.level === 'warning' ? '⚠ Menos del 20 % libre' : '';
      entry.caption.innerHTML =
        `${bytes(partition.free)} libres de ${bytes(partition.total)}` +
        (warning ? `<br><b class="disk-warning">${warning}</b>` : '');
      entry.donut.update({
        used: partition.used,
        total: partition.total,
        level: partition.level,
        center: pct(partition.percent, 0),
        sub: partition.fstype || partition.device || '',
        format: (value) => bytes(value),
      });
    }

    // Una particion desmontada deja de existir: se retira su tarjeta.
    for (const [mount, entry] of this.diskDonuts) {
      if (!seen.has(mount)) {
        entry.donut.destroy();
        entry.card.remove();
        this.diskDonuts.delete(mount);
      }
    }
  }
}
