// Dialogo modal minimo: confirmacion y formularios.
// Devuelve una promesa para poder usar `await confirmDialog(...)` en el sitio
// donde se decide la accion, sin callbacks anidados.

const root = document.getElementById('modal-root');

function mount(render) {
  return new Promise((resolve) => {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    backdrop.appendChild(modal);

    const close = (value) => {
      document.removeEventListener('keydown', onKey);
      backdrop.remove();
      resolve(value);
    };
    const onKey = (event) => { if (event.key === 'Escape') close(null); };

    document.addEventListener('keydown', onKey);
    backdrop.addEventListener('mousedown', (event) => {
      if (event.target === backdrop) close(null);
    });

    render(modal, close);
    root.appendChild(backdrop);
    modal.querySelector('input, select, button')?.focus();
  });
}

// `collect` permite leer campos del propio dialogo (un checkbox, por ejemplo)
// antes de desmontarlo: despues de cerrar, esos nodos ya no estan en el DOM.
export function confirmDialog({ title, body, confirmLabel = 'Confirmar', danger = false,
                                collect = null }) {
  return mount((modal, close) => {
    modal.innerHTML = `
      <h3></h3>
      <div class="modal-body"></div>
      <div class="actions">
        <button type="button" data-action="cancel">Cancelar</button>
        <button type="button" data-action="ok" class="${danger ? 'danger' : 'primary'}"></button>
      </div>`;
    modal.querySelector('h3').textContent = title;
    modal.querySelector('.modal-body').innerHTML = body;
    const ok = modal.querySelector('[data-action="ok"]');
    ok.textContent = confirmLabel;
    ok.addEventListener('click', () => close(collect ? collect(modal) : true));
    modal.querySelector('[data-action="cancel"]').addEventListener('click', () => close(null));
  });
}

export function formDialog({ title, html, confirmLabel = 'Guardar', collect }) {
  return mount((modal, close) => {
    modal.innerHTML = `
      <h3></h3>
      <form><div class="form-body"></div>
        <div class="actions">
          <button type="button" data-action="cancel">Cancelar</button>
          <button type="submit" class="primary"></button>
        </div>
      </form>`;
    modal.querySelector('h3').textContent = title;
    modal.querySelector('.form-body').innerHTML = html;
    modal.querySelector('[type="submit"]').textContent = confirmLabel;
    modal.querySelector('[data-action="cancel"]').addEventListener('click', () => close(null));
    modal.querySelector('form').addEventListener('submit', (event) => {
      event.preventDefault();
      close(collect(modal));
    });
  });
}
