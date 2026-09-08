// Tabla de procesos: orden por columna, filtro y terminacion con confirmacion.
//
// El orden y el filtro se resuelven en el cliente sobre los datos ya recibidos.
// Ir al servidor para reordenar 120 filas que ya estan en memoria seria trabajo
// extra para la Pi sin ninguna ventaja.

import { api } from '../api.js';
import { confirmDialog } from './modal.js';
import { notifyError, notifyOk } from './toast.js';
import { bytes, duration, escapeHtml } from '../format.js';

const $ = (id) => document.getElementById(id);

// Columnas que se ordenan de mayor a menor la primera vez que se pulsan: en
// un monitor interesa antes "quien consume mas" que el orden alfabetico.
const NUMERIC_DESC_FIRST = new Set(['cpu', 'mem', 'rss', 'threads', 'started']);

export class ProcessTable {
  constructor() {
    this.rows = [];
    this.sortKey = 'cpu';
    this.sortDir = -1;
    this.filter = '';
    this.canKill = true;

    this.body = $('proc-body');
    this.empty = $('proc-empty');

    $('proc-table').querySelectorAll('th[data-sort]').forEach((th) => {
      th.addEventListener('click', () => this.setSort(th.dataset.sort));
    });

    let debounce;
    $('proc-filter').addEventListener('input', (event) => {
      clearTimeout(debounce);
      const value = event.target.value.trim().toLowerCase();
      debounce = setTimeout(() => { this.filter = value; this.render(); }, 120);
    });

    // Delegacion: las filas se recrean en cada tick, un listener por boton
    // significaria cientos de listeners nuevos cada pocos segundos.
    this.body.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-pid]');
      if (button) this.confirmKill(Number(button.dataset.pid), button.dataset.name);
    });
  }

  setSort(key) {
    if (this.sortKey === key) {
      this.sortDir *= -1;
    } else {
      this.sortKey = key;
      this.sortDir = NUMERIC_DESC_FIRST.has(key) ? -1 : 1;
    }
    this.render();
  }

  update(data) {
    this.rows = data.processes ?? [];
    this.canKill = data.can_kill !== false;
    $('proc-summary').textContent =
      `${data.shown} de ${data.total} procesos · ` +
      Object.entries(data.by_status ?? {})
        .sort((a, b) => b[1] - a[1]).slice(0, 3)
        .map(([status, count]) => `${count} ${status}`).join(', ');
    this.render();
  }

  visibleRows() {
    const term = this.filter;
    const rows = term
      ? this.rows.filter((row) => row.name.toLowerCase().includes(term)
          || row.user.toLowerCase().includes(term)
          || String(row.pid).includes(term))
      : [...this.rows];

    const key = this.sortKey;
    return rows.sort((a, b) => {
      const left = a[key];
      const right = b[key];
      const result = typeof left === 'number' && typeof right === 'number'
        ? left - right
        : String(left).localeCompare(String(right), 'es');
      return result * this.sortDir;
    });
  }

  render() {
    document.querySelectorAll('#proc-table th[data-sort]').forEach((th) => {
      if (th.dataset.sort === this.sortKey) {
        th.setAttribute('aria-sort', this.sortDir === 1 ? 'ascending' : 'descending');
      } else {
        th.removeAttribute('aria-sort');
      }
    });

    const rows = this.visibleRows();
    this.empty.hidden = rows.length > 0;
    if (!rows.length) {
      this.body.innerHTML = '';
      this.empty.textContent = this.rows.length
        ? 'Ningun proceso coincide con el filtro.'
        : 'Cargando procesos…';
      return;
    }

    this.body.innerHTML = rows.map((row) => `
      <tr>
        <td class="num">${row.pid}</td>
        <td class="name">${escapeHtml(row.name)}</td>
        <td class="dim">${escapeHtml(row.user)}</td>
        <td class="num">${row.cpu.toFixed(1)}</td>
        <td class="num">${row.mem.toFixed(1)}</td>
        <td class="num">${bytes(row.rss)}</td>
        <td class="num">${row.threads}</td>
        <td class="dim">${escapeHtml(row.status)}</td>
        <td class="dim">${duration(Date.now() / 1000 - row.started)}</td>
        <td>${this.canKill
          ? `<button class="danger" data-pid="${row.pid}" data-name="${escapeHtml(row.name)}">Terminar</button>`
          : '<span class="dim">—</span>'}</td>
      </tr>`).join('');
  }

  async confirmKill(pid, name) {
    const confirmed = await confirmDialog({
      title: `Terminar ${name}?`,
      body: `<p>Se enviara <b>SIGTERM</b> al proceso <b>${escapeHtml(name)}</b> (PID ${pid}),
             dandole oportunidad de cerrar de forma limpia.</p>
             <p>Si el proceso ignora la senal seguira vivo; en ese caso puedes reintentar
             con SIGKILL, que lo mata sin permitirle guardar nada.</p>
             <label class="checks" style="margin-top:12px">
               <input type="checkbox" id="kill-force"> Usar SIGKILL directamente
             </label>`,
      confirmLabel: 'Terminar proceso',
      danger: true,
      collect: (modal) => ({ force: modal.querySelector('#kill-force').checked }),
    });
    if (!confirmed) return;

    const { force } = confirmed;
    try {
      const result = await api.del(`/api/processes/${pid}?force=${force}`);
      if (result.terminated) {
        notifyOk(`${result.name} (PID ${pid}) terminado con ${result.signal}.`);
      } else {
        notifyError(`${result.name} recibio ${result.signal} pero sigue vivo. Prueba con SIGKILL.`);
      }
      this.rows = this.rows.filter((row) => row.pid !== pid || !result.terminated);
      this.render();
    } catch (error) {
      notifyError(error.message);
    }
  }
}
