# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
`docker-update.sh` muestra la sección de la versión nueva al actualizar.

## [1.0.0] - 2026-09-08

Primera versión.

### Panel
- Métricas en vivo por WebSocket: CPU (global, por núcleo, frecuencia,
  temperatura y estado de *throttling* de la Raspberry Pi), RAM y swap,
  particiones con aviso por debajo del 10 % libre, tabla de procesos ordenable
  con terminación controlada, conexiones activas y ancho de banda.
- Un único bucle de muestreo hace *broadcast* a todos los clientes, en tres
  cadencias. Los colectores caros solo se ejecutan si alguien está suscrito a
  ese canal, así que las pestañas que nadie mira no cuestan nada.
- Histórico en SQLite con una fila por minuto (media más pico de CPU) y purga
  automática por edad.
- Alertas por umbral con duración mínima, histéresis y silencio entre disparos,
  con envío a log, webhook, Telegram o Discord.
- Diseño responsive en modo oscuro, con paleta validada para daltonismo y
  contraste. Ningún estado se comunica solo con color.
- `/health` público que devuelve 503 si el bucle de muestreo se para.

### Seguridad
- Autenticación con Argon2id y sesión en JWT dentro de una cookie httpOnly.
  Cerrar sesión invalida el token en el servidor, no solo borra la cookie.
- Bloqueo temporal por IP tras varios intentos fallidos.
- Cabecera `Host` validada contra DNS rebinding y `Origin` validado en el
  handshake del WebSocket (*cross-site WebSocket hijacking*).
- CSP con `script-src 'self'`, más `X-Frame-Options`, `nosniff` y
  `Referrer-Policy`.
- La terminación de procesos respeta `SM_ALLOW_KILL_FOREIGN` también cuando el
  monitor corre como root, y queda registrada en una tabla de auditoría.
- El log distingue las tres causas de un login rechazado (usuario distinto,
  contraseña distinta, hash mal configurado), que desde fuera son la misma
  respuesta.

### Despliegue
- Contenedor único con acceso a `/proc` y `/sys` del host, para amd64 y arm64.
- `docker-up.sh`: primer arranque guiado. Crea el `.env`, genera la clave de
  sesión, pregunta el puerto y las credenciales, comprueba que el host sirva
  para lo que el compose pide, y verifica que el hash llegue intacto al
  contenedor antes de dar la URL por buena.
- `docker-update.sh`: copia previa de la base de datos, comprobación de que la
  versión nueva arranca y vuelta atrás automática a la imagen anterior.
- Unidad de systemd para quien prefiera instalarlo nativo.
