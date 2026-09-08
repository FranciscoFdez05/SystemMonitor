// Cliente WebSocket con reconexion escalonada y suscripcion dinamica.
//
// La suscripcion es el mecanismo que mantiene baja la carga del servidor: al
// cambiar de pestana se renuncia a los canales que ya no se miran, y el
// scheduler deja de ejecutar esos colectores.

const CLOSE_UNAUTHORIZED = 4401;
const MAX_BACKOFF_MS = 15000;

export class MetricsSocket extends EventTarget {
  constructor() {
    super();
    this.socket = null;
    this.channels = new Set();
    this.state = 'connecting';
    this.attempts = 0;
    this.reconnectTimer = null;
    this.manualClose = false;
  }

  connect() {
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) return;
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    this.setState('connecting');
    this.socket = new WebSocket(`${scheme}://${location.host}/ws`);

    this.socket.addEventListener('open', () => {
      this.attempts = 0;
      this.setState('online');
      this.sendSubscription();
    });

    this.socket.addEventListener('message', (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      if (message.type === 'metrics') {
        this.dispatchEvent(new CustomEvent(`metrics:${message.channel}`, { detail: message.data }));
      } else {
        this.dispatchEvent(new CustomEvent(message.type, { detail: message.data }));
      }
    });

    this.socket.addEventListener('close', (event) => {
      if (this.manualClose) return;
      if (event.code === CLOSE_UNAUTHORIZED) {
        // La sesion ha caducado: reconectar en bucle solo daria 401 sin fin.
        this.setState('offline');
        window.location.href = '/login';
        return;
      }
      this.setState('offline');
      this.scheduleReconnect();
    });

    this.socket.addEventListener('error', () => this.socket?.close());
  }

  scheduleReconnect() {
    clearTimeout(this.reconnectTimer);
    // Backoff exponencial con techo: una Pi reiniciandose no merece una
    // tormenta de reconexiones, pero tampoco esperas de minutos.
    const delay = Math.min(500 * 2 ** this.attempts, MAX_BACKOFF_MS);
    this.attempts += 1;
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }

  setState(state) {
    this.state = state;
    this.dispatchEvent(new CustomEvent('state', { detail: state }));
  }

  subscribe(channels) {
    const next = new Set(channels);
    const same = next.size === this.channels.size && [...next].every((c) => this.channels.has(c));
    if (same) return;
    this.channels = next;
    this.sendSubscription();
  }

  sendSubscription() {
    if (this.socket?.readyState !== WebSocket.OPEN) return;
    this.socket.send(JSON.stringify({ action: 'subscribe', channels: [...this.channels] }));
  }

  close() {
    this.manualClose = true;
    clearTimeout(this.reconnectTimer);
    this.socket?.close();
  }
}
