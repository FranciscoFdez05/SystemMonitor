// Formulario de acceso. Va en un fichero aparte y no como <script> en linea
// porque la CSP del panel usa script-src 'self': un script embebido en el HTML
// quedaria bloqueado, que es justo lo que se quiere frente a un XSS.

const form = document.getElementById('login-form');
const errorBox = document.getElementById('login-error');
const submit = document.getElementById('submit');

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  errorBox.hidden = true;
  submit.disabled = true;
  submit.textContent = 'Comprobando…';
  try {
    const response = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: form.username.value,
        password: form.password.value,
      }),
    });
    if (response.ok) {
      // La cookie de sesion ya viene puesta en la respuesta.
      window.location.href = '/';
      return;
    }
    const data = await response.json().catch(() => ({}));
    showError(data.detail || 'No se pudo iniciar sesion');
    form.password.value = '';
    form.password.focus();
  } catch {
    showError('No hay conexion con el servidor');
  } finally {
    submit.disabled = false;
    submit.textContent = 'Entrar';
  }
});
