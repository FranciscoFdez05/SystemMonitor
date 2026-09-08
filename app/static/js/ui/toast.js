// Avisos efimeros en la esquina inferior. El nivel se refleja en el borde y en
// el titulo del texto, nunca solo en el color.

const container = document.getElementById('toasts');
const DEFAULT_MS = 5000;

export function toast(message, { level = 'info', title = '', timeout = DEFAULT_MS } = {}) {
  const el = document.createElement('div');
  el.className = 'toast';
  el.dataset.level = level;
  if (title) {
    const head = document.createElement('div');
    head.className = 'toast-title';
    head.textContent = title;
    el.appendChild(head);
  }
  const body = document.createElement('div');
  body.textContent = message;
  el.appendChild(body);
  container.appendChild(el);

  const remove = () => el.remove();
  const timer = setTimeout(remove, timeout);
  el.addEventListener('click', () => { clearTimeout(timer); remove(); });
  return el;
}

export const notifyError = (message) => toast(message, { level: 'error', title: 'Error' });
export const notifyOk = (message) => toast(message, { level: 'success' });
