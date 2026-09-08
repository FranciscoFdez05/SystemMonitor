// Panel de alertas: reglas de umbral, historial de disparos y prueba de sinks.

import { api } from '../api.js';
import { confirmDialog, formDialog } from './modal.js';
import { notifyError, notifyOk, toast } from './toast.js';
import { dateTime, duration, escapeHtml, relative } from '../format.js';

const $ = (id) => document.getElementById(id);

const SINK_LABELS = { log: 'Log', webhook: 'Webhook', telegram: 'Telegram', discord: 'Discord' };

export class AlertsPanel {
  constructor() {
    this.rules = [];
    this.metrics = {};
    this.sinks = {};
    this.firing = 0;

    $('rule-new').addEventListener('click', () => this.editRule(null));
    $('rules-body').addEventListener('click', (event) => {
      const button = event.target.closest('button[data-action]');
      if (!button) return;
      const rule = this.rules.find((r) => r.id === Number(button.dataset.id));
      if (!rule) return;
      if (button.dataset.action === 'edit') this.editRule(rule);
      if (button.dataset.action === 'delete') this.deleteRule(rule);
      if (button.dataset.action === 'toggle') this.toggleRule(rule);
    });
    $('sink-tests').addEventListener('click', (event) => {
      const button = event.target.closest('button[data-sink]');
      if (button) this.testSink(button.dataset.sink);
    });
  }

  async load() {
    try {
      const [rulesData, eventsData] = await Promise.all([
        api.get('/api/alerts/rules'),
        api.get('/api/alerts/events?limit=50'),
      ]);
      this.rules = rulesData.rules;
      this.metrics = rulesData.metrics;
      this.sinks = rulesData.sinks;
      this.renderRules();
      this.renderSinkTests();
      this.renderEvents(eventsData.events);
    } catch (error) {
      notifyError(`No se pudieron cargar las alertas: ${error.message}`);
    }
  }

  renderRules() {
    this.firing = this.rules.filter((rule) => rule.firing).length;
    const badge = $('alert-badge');
    badge.hidden = this.firing === 0;
    badge.textContent = this.firing;

    $('rules-body').innerHTML = this.rules.map((rule) => {
      // Estado con icono y palabra: nunca solo el color.
      const state = !rule.enabled ? '<span class="badge-chip">⏸ Pausada</span>'
        : rule.firing ? '<span class="badge-chip" data-level="critical">⚠ Disparada</span>'
        : '<span class="badge-chip" data-level="good">✓ Normal</span>';
      const value = rule.value === null || rule.value === undefined
        ? '—' : rule.value.toFixed(1);
      return `
        <tr>
          <td>${state}</td>
          <td class="name">${escapeHtml(rule.name)}</td>
          <td class="dim">${escapeHtml(rule.description)}</td>
          <td class="num">${value}</td>
          <td class="dim">${duration(rule.duration_s)}</td>
          <td class="dim">${duration(rule.cooldown_s)}</td>
          <td class="dim">${rule.sinks.map((s) => SINK_LABELS[s] ?? s).join(', ')}</td>
          <td style="white-space:nowrap">
            <button data-action="toggle" data-id="${rule.id}">${rule.enabled ? 'Pausar' : 'Activar'}</button>
            <button data-action="edit" data-id="${rule.id}">Editar</button>
            <button data-action="delete" data-id="${rule.id}" class="danger">Borrar</button>
          </td>
        </tr>`;
    }).join('');
  }

  renderSinkTests() {
    $('sink-tests').innerHTML = Object.entries(this.sinks).map(([name, available]) => `
      <button data-sink="${name}" ${available ? '' : 'disabled'}
              title="${available ? 'Enviar una notificacion de prueba' : 'Sin configurar en el .env'}">
        ${SINK_LABELS[name] ?? name}${available ? '' : ' (sin configurar)'}
      </button>`).join('');
  }

  renderEvents(events) {
    $('events-empty').hidden = events.length > 0;
    $('events-body').innerHTML = events.map((event) => {
      const firing = event.state === 'firing';
      const delivery = Object.entries(event.delivery ?? {})
        .map(([sink, result]) => `${SINK_LABELS[sink] ?? sink}: ${result}`).join(' · ');
      return `
        <tr>
          <td class="dim" title="${dateTime(event.ts)}">hace ${relative(event.ts)}</td>
          <td class="name">${escapeHtml(event.rule_name ?? '—')}</td>
          <td><span class="badge-chip" data-level="${firing ? 'critical' : 'good'}">
              ${firing ? '⚠ Disparada' : '✓ Resuelta'}</span></td>
          <td class="num">${event.value}</td>
          <td class="num">${event.threshold}</td>
          <td class="dim">${escapeHtml(delivery || '—')}</td>
        </tr>`;
    }).join('');
  }

  ruleFormHtml(rule) {
    const metricOptions = Object.entries(this.metrics).map(([key, label]) =>
      `<option value="${key}" ${rule?.metric === key ? 'selected' : ''}>${escapeHtml(label)}</option>`
    ).join('');
    const sinkChecks = Object.entries(this.sinks).map(([name, available]) => `
      <label><input type="checkbox" name="sink" value="${name}"
        ${rule?.sinks?.includes(name) ? 'checked' : ''} ${available ? '' : 'disabled'}>
        ${SINK_LABELS[name] ?? name}${available ? '' : ' (sin configurar)'}</label>`).join('');

    return `
      <div class="field">
        <label for="f-name">Nombre</label>
        <input type="text" id="f-name" value="${escapeHtml(rule?.name ?? '')}" required maxlength="80">
      </div>
      <div class="field-row">
        <div class="field">
          <label for="f-metric">Metrica</label>
          <select id="f-metric">${metricOptions}</select>
        </div>
        <div class="field">
          <label for="f-target">Punto de montaje</label>
          <input type="text" id="f-target" value="${escapeHtml(rule?.target ?? '')}" placeholder="/">
          <span class="hint">Solo para la metrica de disco.</span>
        </div>
      </div>
      <div class="field-row">
        <div class="field">
          <label for="f-operator">Condicion</label>
          <select id="f-operator">
            <option value="gt" ${rule?.operator !== 'lt' ? 'selected' : ''}>Mayor que</option>
            <option value="lt" ${rule?.operator === 'lt' ? 'selected' : ''}>Menor que</option>
          </select>
        </div>
        <div class="field">
          <label for="f-threshold">Umbral</label>
          <input type="number" id="f-threshold" step="0.1" value="${rule?.threshold ?? 90}" required>
        </div>
      </div>
      <div class="field-row">
        <div class="field">
          <label for="f-duration">Debe mantenerse (segundos)</label>
          <input type="number" id="f-duration" min="0" max="86400" value="${rule?.duration_s ?? 60}">
          <span class="hint">Evita alertas por un pico de un par de segundos.</span>
        </div>
        <div class="field">
          <label for="f-cooldown">Silencio tras disparar (segundos)</label>
          <input type="number" id="f-cooldown" min="0" max="86400" value="${rule?.cooldown_s ?? 900}">
          <span class="hint">Sin esto, un disco lleno avisa cada minuto.</span>
        </div>
      </div>
      <div class="field">
        <label>Notificar a</label>
        <div class="checks">${sinkChecks}</div>
      </div>
      <div class="field">
        <label class="checks"><input type="checkbox" id="f-enabled"
          ${rule === null || rule.enabled ? 'checked' : ''}> Regla activa</label>
      </div>`;
  }

  async editRule(rule) {
    const payload = await formDialog({
      title: rule ? `Editar "${rule.name}"` : 'Nueva regla de alerta',
      html: this.ruleFormHtml(rule),
      confirmLabel: rule ? 'Guardar cambios' : 'Crear regla',
      collect: (modal) => ({
        name: modal.querySelector('#f-name').value.trim(),
        metric: modal.querySelector('#f-metric').value,
        target: modal.querySelector('#f-target').value.trim(),
        operator: modal.querySelector('#f-operator').value,
        threshold: Number(modal.querySelector('#f-threshold').value),
        duration_s: Number(modal.querySelector('#f-duration').value),
        cooldown_s: Number(modal.querySelector('#f-cooldown').value),
        sinks: [...modal.querySelectorAll('input[name="sink"]:checked')].map((el) => el.value),
        enabled: modal.querySelector('#f-enabled').checked,
      }),
    });
    if (!payload) return;
    if (!payload.sinks.length) payload.sinks = ['log'];

    try {
      if (rule) await api.put(`/api/alerts/rules/${rule.id}`, payload);
      else await api.post('/api/alerts/rules', payload);
      notifyOk(rule ? 'Regla actualizada.' : 'Regla creada.');
      await this.load();
    } catch (error) {
      notifyError(error.message);
    }
  }

  async toggleRule(rule) {
    try {
      await api.put(`/api/alerts/rules/${rule.id}`, { ...rule, enabled: !rule.enabled });
      await this.load();
    } catch (error) {
      notifyError(error.message);
    }
  }

  async deleteRule(rule) {
    const confirmed = await confirmDialog({
      title: 'Borrar regla?',
      body: `<p>Se eliminara <b>${escapeHtml(rule.name)}</b>. Los disparos ya registrados se conservan.</p>`,
      confirmLabel: 'Borrar',
      danger: true,
    });
    if (!confirmed) return;
    try {
      await api.del(`/api/alerts/rules/${rule.id}`);
      notifyOk('Regla borrada.');
      await this.load();
    } catch (error) {
      notifyError(error.message);
    }
  }

  async testSink(name) {
    try {
      const result = await api.post(`/api/alerts/test/${name}`);
      if (result.ok) notifyOk(`${SINK_LABELS[name] ?? name}: envio correcto (${result.detail}).`);
      else notifyError(`${SINK_LABELS[name] ?? name}: ${result.detail}`);
    } catch (error) {
      notifyError(error.message);
    }
  }

  // Un evento llegado por WebSocket: se avisa aunque el usuario este en otra pestana.
  onAlertEvent(event) {
    const firing = event.state === 'firing';
    toast(`${event.rule_name}: ${event.metric}${event.target ? ` (${event.target})` : ''} = ${event.value}`, {
      level: firing ? 'error' : 'success',
      title: firing ? '⚠ Alerta disparada' : '✓ Alerta resuelta',
      timeout: firing ? 12000 : 6000,
    });
    this.load();
  }
}
