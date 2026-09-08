// Envoltorio de fetch. Centraliza dos cosas: el 401 que debe llevar al login
// y el mensaje de error que muestra la interfaz.

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (response.status === 401) {
    window.location.href = '/login';
    throw new Error('Sesion caducada');
  }
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(data?.detail || `Error ${response.status}`);
  }
  return data;
}

export const api = {
  get: (url) => request(url),
  post: (url, body) => request(url, { method: 'POST', body: JSON.stringify(body ?? {}) }),
  put: (url, body) => request(url, { method: 'PUT', body: JSON.stringify(body ?? {}) }),
  del: (url) => request(url, { method: 'DELETE' }),
};
