# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
`docker-update.sh` muestra la sección de la versión nueva al actualizar.

## [1.1.0] - 2026-09-08

### Añadido
- `docker-up.sh`: primer arranque guiado. Crea el `.env`, genera `SM_SECRET_KEY`,
  pide usuario y contraseña, comprueba que el puerto esté libre y que el host
  sea Linux de verdad, espera al healthcheck y verifica que el login responde.
- `docker-update.sh`: actualización con copia previa de la base de datos,
  comprobación de que la versión nueva arranca y vuelta atrás automática.
- `app/version.py` como origen único de la versión, y la imagen etiquetada con
  ella para que la vuelta atrás tenga a dónde volver.
- `app/tools/hashpw.py --stdin` para generar el hash de forma no interactiva.

### Corregido
- `SM_ALLOW_KILL_FOREIGN` se ignoraba cuando el monitor corría como root, que es
  justo cuando hace falta.
- Cierre del WebSocket: esperar a las tareas canceladas provocaba un
  `CancelledError` intermitente al cerrar la pestaña.
- El acumulador del histórico se vaciaba después de escribir en SQLite y perdía
  las muestras que llegaban durante la escritura.
- El submuestreo del histórico truncaba el cubo y devolvía más puntos de los
  pedidos.
- `signal.SIGKILL` no existe en Windows y la terminación forzada daba un 500.
- Importar `app.core.security` exigía credenciales, lo que impedía usar la
  herramienta que sirve precisamente para crearlas.

### Seguridad
- Cabecera `Host` validada contra DNS rebinding.
- `Origin` validado en el handshake del WebSocket (cross-site WebSocket
  hijacking).
- CSP con `script-src 'self'`, más `X-Frame-Options`, `nosniff` y
  `Referrer-Policy`.
- Cerrar sesión invalida el token en el servidor, no solo borra la cookie.
- Comparación del usuario en tiempo constante y `SM_COOKIE_SECURE` configurable.

## [1.0.0] - 2026-09-08

### Añadido
- Panel de monitorización con métricas en vivo por WebSocket: CPU (global, por
  núcleo, frecuencia, temperatura y throttling), RAM y swap, particiones,
  procesos y conexiones de red.
- Histórico en SQLite con agregados por minuto y purga automática.
- Alertas por umbral con duración mínima, histéresis y cooldown, con envío a
  log, webhook, Telegram o Discord.
- Autenticación con Argon2id y sesión en cookie httpOnly.
- Despliegue en contenedor único con acceso a `/proc` y `/sys` del host.
