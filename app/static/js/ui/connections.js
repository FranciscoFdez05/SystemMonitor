// Panel de red: ancho de banda, conexiones activas y procesos con mas sockets.

import { COLORS } from '../charts/base.js';
import { RealtimeChart } from '../charts/realtime.js';
import { bps, bytes, clockTime, escapeHtml } from '../format.js';

const $ = (id) => document.getElementById(id);

export class NetworkPanel {
  constructor({ fastInterval }) {
    const points = Math.max(60, Math.round(300 / fastInterval));
    this.chart = new RealtimeChart($('chart-net2'), {
      series: [
        { label: 'Bajada', color: COLORS.series[0] },
        { label: 'Subida', color: COLORS.series[1] },
      ],
      maxPoints: points,
      format: (v) => bps(v),
      stableAxis: { floor: 64 * 1024, decayTicks: 20 },
    });

    this.connections = [];
    this.sortKey = 'status';
    this.sortDir = 1;
    this.filter = '';
    this.stateFilter = '';

    $('conn-table').querySelectorAll('th[data-sort]').forEach((th) => {
      th.addEventListener('click', () => {
        if (this.sortKey === th.dataset.sort) this.sortDir *= -1;
        else { this.sortKey = th.dataset.sort; this.sortDir = 1; }
        this.render();
      });
    });

    let debounce;
    $('conn-filter').addEventListener('input', (event) => {
      clearTimeout(debounce);
      const value = event.target.value.trim().toLowerCase();
      debounce = setTimeout(() => { this.filter = value; this.render(); }, 120);
    });
    $('conn-state').addEventListener('change', (event) => {
      this.stateFilter = event.target.value;
      this.render();
    });
  }

  updateBandwidth(data) {
    this.chart.push(clockTime(Date.now() / 1000), [data.rx_bps, data.tx_bps]);
    $('net-panel-now').textContent = `↓ ${bps(data.rx_bps)} · ↑ ${bps(data.tx_bps)}`;

    const nics = Object.entries(data.nics ?? {});
    $('nic-list').innerHTML = nics.map(([name, info]) => `
      <span class="badge-chip">${escapeHtml(name)}: ↓ ${bps(info.rx_bps)} ↑ ${bps(info.tx_bps)}
      · total ${bytes(info.rx_total + info.tx_total)}</span>`).join('');
  }

  updateConnections(data) {
    this.connections = data.connections ?? [];
    $('conn-degraded').hidden = !data.degraded;
    $('conn-summary').textContent =
      `${data.total} conexiones` + (data.truncated ? ' (se muestran las 500 primeras)' : '') +
      ' · ' + Object.entries(data.states ?? {})
        .sort((a, b) => b[1] - a[1]).slice(0, 4)
        .map(([state, count]) => `${count} ${state}`).join(', ');

    const talkers = data.top_talkers ?? [];
    $('talkers-body').innerHTML = talkers.length
      ? talkers.map((row) => `
          <tr>
            <td class="name">${escapeHtml(row.name || '?')}</td>
            <td class="num">${row.pid}</td>
            <td class="num">${row.established}</td>
            <td class="num">${row.listening}</td>
            <td class="num">${row.count}</td>
          </tr>`).join('')
      : '<tr><td colspan="5" class="dim">Sin datos por proceso.</td></tr>';

    this.render();
  }

  render() {
    const term = this.filter;
    let rows = this.connections;
    if (this.stateFilter) rows = rows.filter((row) => row.status === this.stateFilter);
    if (term) {
      rows = rows.filter((row) => row.laddr.toLowerCase().includes(term)
        || row.raddr.toLowerCase().includes(term)
        || (row.name || '').toLowerCase().includes(term)
        || String(row.pid ?? '').includes(term));
    }

    const key = this.sortKey;
    rows = [...rows].sort((a, b) => {
      const left = a[key] ?? '';
      const right = b[key] ?? '';
      const result = typeof left === 'number' && typeof right === 'number'
        ? left - right
        : String(left).localeCompare(String(right), 'es');
      return result * this.sortDir;
    });

    document.querySelectorAll('#conn-table th[data-sort]').forEach((th) => {
      if (th.dataset.sort === key) {
        th.setAttribute('aria-sort', this.sortDir === 1 ? 'ascending' : 'descending');
      } else {
        th.removeAttribute('aria-sort');
      }
    });

    $('conn-empty').hidden = rows.length > 0;
    if (!rows.length) {
      $('conn-body').innerHTML = '';
      $('conn-empty').textContent = this.connections.length
        ? 'Ninguna conexion coincide con el filtro.'
        : 'No hay conexiones que mostrar.';
      return;
    }

    $('conn-body').innerHTML = rows.map((row) => `
      <tr>
        <td class="dim">${escapeHtml(row.proto)}</td>
        <td class="num" style="text-align:left">${escapeHtml(row.laddr)}</td>
        <td class="num" style="text-align:left">${escapeHtml(row.raddr || '—')}</td>
        <td class="dim">${escapeHtml(row.status)}</td>
        <td class="num">${row.pid ?? '—'}</td>
        <td class="name">${escapeHtml(row.name || '—')}</td>
      </tr>`).join('');
  }
}
