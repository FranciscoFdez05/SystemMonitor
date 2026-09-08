// Arranque y orquestacion del dashboard.
//
// Aqui vive la logica de suscripcion: cada pestana declara que canales
// necesita, y al cambiar de pestana se renuncia a los demas. El servidor deja
// entonces de ejecutar los colectores caros que nadie esta mirando.

import { api } from './api.js';
import { applyDefaults } from './charts/base.js';
import { AlertsPanel } from './ui/alerts.js';
import { NetworkPanel } from './ui/connections.js';
import { HistoryPanel } from './ui/history.js';
import { Overview } from './ui/overview.js';
import { ProcessTable } from './ui/processes.js';
import { toast } from './ui/toast.js';
import { MetricsSocket } from './ws-client.js';

const $ = (id) => document.getElementById(id);

// Canales siempre necesarios: alimentan la barra superior y las tarjetas de
// cifras, que se ven desde cualquier pestana.
const BASE_CHANNELS = ['cpu', 'memory', 'thermal', 'network', 'system'];

const PANEL_CHANNELS = {
  overview: [...BASE_CHANNELS, 'disk'],
  processes: [...BASE_CHANNELS, 'processes'],
  network: [...BASE_CHANNELS, 'connections'],
  history: BASE_CHANNELS,
  alerts: BASE_CHANNELS,
};

class Dashboard {
  constructor() {
    applyDefaults();
    const fastInterval = Number(document.body.dataset.fastInterval || 2);

    this.overview = new Overview({ fastInterval });
    this.processes = new ProcessTable();
    this.network = new NetworkPanel({ fastInterval });
    this.history = new HistoryPanel();
    this.alerts = new AlertsPanel();

    this.socket = new MetricsSocket();
    this.panel = 'overview';
    this.historyLoaded = false;

    this.wireTabs();
    this.wireSocket();
    this.wireChrome();
  }

  start() {
    this.socket.connect();
    this.socket.subscribe(PANEL_CHANNELS[this.panel]);
    this.alerts.load();
  }

  // ------------------------------------------------------------------ tabs
  wireTabs() {
    document.querySelectorAll('.tab').forEach((tab) => {
      tab.addEventListener('click', () => this.showPanel(tab.dataset.panel));
    });
    // El hash permite recargar y volver a la misma pestana.
    const initial = location.hash.slice(1);
    if (PANEL_CHANNELS[initial]) this.showPanel(initial);
  }

  showPanel(name) {
    if (!PANEL_CHANNELS[name]) return;
    this.panel = name;
    history.replaceState(null, '', `#${name}`);

    document.querySelectorAll('.tab').forEach((tab) => {
      tab.setAttribute('aria-selected', String(tab.dataset.panel === name));
    });
    document.querySelectorAll('.panel').forEach((panel) => {
      panel.hidden = panel.id !== `panel-${name}`;
    });

    this.socket.subscribe(PANEL_CHANNELS[name]);

    if (name === 'history' && !this.historyLoaded) {
      this.historyLoaded = true;
      this.history.rebuild();
      this.history.load();
    }
    if (name === 'alerts') this.alerts.load();
  }

  // ---------------------------------------------------------------- socket
  wireSocket() {
    const on = (event, handler) => this.socket.addEventListener(event, (e) => handler(e.detail));

    on('metrics:cpu', (data) => this.overview.updateCpu(data));
    on('metrics:memory', (data) => this.overview.updateMemory(data));
    on('metrics:thermal', (data) => this.overview.updateThermal(data));
    on('metrics:system', (data) => this.overview.updateSystem(data));
    on('metrics:disk', (data) => this.overview.updateDisk(data));
    on('metrics:processes', (data) => this.processes.update(data));
    on('metrics:connections', (data) => this.network.updateConnections(data));
    on('metrics:network', (data) => {
      this.overview.updateNetwork(data);
      this.network.updateBandwidth(data);
    });

    on('alert', (event) => this.alerts.onAlertEvent(event));
    on('process_killed', (event) => {
      toast(`${event.name} (PID ${event.pid}) terminado por ${event.by}.`, { level: 'warning' });
    });

    this.socket.addEventListener('state', (event) => this.renderConnectionState(event.detail));
  }

  renderConnectionState(state) {
    const labels = {
      online: 'En vivo',
      offline: 'Sin conexion — reintentando',
      connecting: 'Conectando…',
    };
    $('conn').dataset.state = state;
    $('conn-text').textContent = labels[state] ?? state;
  }

  // ---------------------------------------------------------------- chrome
  wireChrome() {
    $('logout').addEventListener('click', async () => {
      this.socket.close();
      await api.post('/api/logout').catch(() => {});
      window.location.href = '/login';
    });

    // Con la pestana en segundo plano no hay nada que dibujar: soltar los
    // canales evita que el servidor siga muestreando para nadie.
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) this.socket.subscribe(BASE_CHANNELS);
      else this.socket.subscribe(PANEL_CHANNELS[this.panel]);
    });
  }
}

const dashboard = new Dashboard();
dashboard.start();
