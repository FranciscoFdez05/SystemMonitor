# SystemMonitor

[![CI](https://github.com/FranciscoFdez05/SystemMonitor/actions/workflows/ci.yml/badge.svg)](https://github.com/FranciscoFdez05/SystemMonitor/actions/workflows/ci.yml)
![versión](https://img.shields.io/badge/versi%C3%B3n-1.0.0-blue)
![python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![licencia](https://img.shields.io/badge/licencia-MIT-green)
![FastAPI](https://img.shields.io/badge/FastAPI-WebSockets-009688)
![SQLite](https://img.shields.io/badge/SQLite-hist%C3%B3rico-003B57)
![arquitectura](https://img.shields.io/badge/docker-arm64%20%7C%20amd64-2496ED)

Panel de monitorización en tiempo real para Raspberry Pi (Ubuntu Server), accesible
desde cualquier dispositivo de la red local. FastAPI + WebSockets + SQLite, servido
en un único contenedor.

- **RAM**: uso en % y GB, donut en vivo, histórico de 24 h.
- **Almacenamiento**: donut por partición, aviso cuando queda menos del 10 % libre.
- **CPU**: uso global y por núcleo, temperatura, frecuencia y estado de *throttling*.
- **Procesos**: tabla ordenable con PID, nombre, CPU, RAM y usuario; terminación con confirmación.
- **Red**: conexiones activas, ancho de banda en vivo y procesos con más sockets abiertos.
- **Alertas**: umbrales configurables con notificación a log, webhook, Telegram o Discord.
- **Histórico**: SQLite con agregados por minuto y purga automática.

---

## Puesta en marcha

```bash
git clone https://github.com/FranciscoFdez05/SystemMonitor.git systemmonitor && cd systemmonitor
./docker-up.sh
```

Eso es todo. El script se encarga del primer arranque:

1. Crea el `.env` a partir de `.env.example` y genera `SM_SECRET_KEY`.
2. **Te pregunta el puerto** (por defecto 7000) y comprueba que esté libre antes
   de construir nada. También comprueba Docker y que el host sea Linux de verdad
   (con Docker Desktop, `pid: host` daría los procesos de la VM, no los tuyos).
3. Construye la imagen y **te pide usuario y contraseña**. El hash Argon2 se
   genera dentro de la imagen recién construida, con los mismos parámetros que
   usará el login; la contraseña en claro no se guarda en ningún sitio.
4. Levanta el contenedor, espera a que `/health` responda y comprueba que el
   login funciona antes de darte la URL.

No lo ejecutes con `sudo`: dejaría el `.env` como root y el siguiente arranque
normal fallaría. Si Docker te pide permisos, añade tu usuario al grupo:
`sudo usermod -aG docker $USER` y vuelve a iniciar sesión.

### Actualizar

```bash
./docker-update.sh
```

Saca una copia consistente de la base de datos (SQLite en WAL no se puede copiar
con `cp` en caliente), trae los cambios, reconstruye, y **comprueba que la
versión nueva arranca**. Si no responde en 90 s, vuelve sola a la imagen
anterior: cada versión queda etiquetada, así que la vuelta atrás es inmediata en
vez de una reconstrucción desde el código viejo.

`./docker-update.sh --sin-pull` reconstruye sin traer código nuevo.

### A mano, sin los scripts

```bash
cp .env.example .env
nano .env                      # SM_USERNAME y SM_PASSWORD, como mínimo
docker compose -f deploy/docker-compose.yml up -d --build
curl http://localhost:7000/health
docker compose -f deploy/docker-compose.yml logs -f
```

Para no dejar la contraseña en claro en el `.env`:

```bash
docker compose -f deploy/docker-compose.yml exec systemmonitor python -m app.tools.hashpw
# copia la línea SM_PASSWORD_HASH=... al .env y borra SM_PASSWORD
```

### Por qué el compose necesita lo que necesita

| Ajuste | Motivo |
|---|---|
| `pid: host` | Sin compartir el *PID namespace*, psutil solo vería el proceso del propio contenedor. |
| `network_mode: host` | Las conexiones y los contadores de tráfico del contenedor no interesan; se quieren los del host. Ojo: con esto `ports:` se ignora y manda `SM_PORT`. |
| `/:/host/root:ro` | `statvfs` necesita una ruta real: el espacio en disco no se puede leer de `/proc`. |
| `/sys:/host/sys:ro` | Temperatura (`/sys/class/thermal`) y estado de *throttling* de la Pi. |
| `/etc/passwd:ro` | Opcional. Sin él, los procesos del host salen con el UID numérico en vez del nombre de usuario. |

Si tienes particiones extra montadas bajo `/` y no aparecen, el *bind* no está
propagando los submontajes: pásalo a la forma larga con `bind.propagation: rslave`,
o enuméralas en `SM_EXTRA_MOUNTS`.

## Instalación nativa (sin Docker)

```bash
sudo useradd --system --create-home --home-dir /opt/systemmonitor monitor
sudo -u monitor git clone https://github.com/FranciscoFdez05/SystemMonitor.git /opt/systemmonitor
cd /opt/systemmonitor
sudo -u monitor python3 -m venv .venv
sudo -u monitor .venv/bin/pip install -r requirements.txt
sudo -u monitor cp .env.example .env && sudo -u monitor nano .env
sudo cp deploy/systemmonitor.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now systemmonitor
```

Ejecutándose nativo, `SM_HOST_ROOT` y `SM_SYS_PATH` se quedan en `/` y `/sys`, y
`vcgencmd` queda disponible como fuente de temperatura y de estado de *throttling*.

---

## Decisiones de diseño

### Un solo muestreo para todos los clientes

El error habitual es muestrear por conexión. Aquí hay un único bucle que llama a
psutil y hace *broadcast* del mismo resultado: **una pestaña abierta o seis cuestan
lo mismo**. Sobre eso, tres cadencias distintas:

| Tick | Cada | Qué recoge | Coste |
|---|---|---|---|
| rápido | `SM_FAST_INTERVAL` (2 s) | CPU, RAM, temperatura, frecuencia, ancho de banda | lecturas de contadores, microsegundos |
| lento | `SM_SLOW_INTERVAL` (6 s) | particiones, procesos, conexiones | recorre `/proc` entero |
| persistencia | `SM_PERSIST_INTERVAL` (60 s) | vuelca el agregado del minuto a SQLite | despreciable |

Y la pieza que más ahorra: **los colectores caros solo se ejecutan si alguien está
suscrito a ese canal**. Si nadie mira la pestaña de procesos, no se recorre `/proc`.
Al ocultar la pestaña del navegador, el cliente suelta los canales pesados solo.
El coste del propio monitor se muestra en la barra superior; en una Pi 4 ronda
50-60 MB de RSS y menos del 2 % de CPU.

### Histórico que no llena la tarjeta SD

Guardar una muestra de 2 s serían 43 200 filas al día. En su lugar se escribe **una
fila por minuto** con la media del minuto **más el pico de CPU**, porque un pico corto
desaparece al promediar y suele ser justo lo que se busca. Una semana ocupa alrededor
de 1 MB. `SM_RETENTION_DAYS` controla la purga, que corre cada hora y usa
`incremental_vacuum` en vez de un `VACUUM` completo: reescribir el fichero entero
castiga la escritura de una SD.

### Alertas que no se convierten en ruido

Tres mecanismos contra la tormenta de notificaciones:

- **Duración mínima**: la condición debe mantenerse N segundos, no basta un pico.
- **Histéresis** de 3 puntos: una regla que salta a 90 no se resuelve hasta bajar de 87.
- **Cooldown**: silencio entre disparos; sin él, un disco lleno avisa cada minuto.

Un sink caído (webhook, Telegram) se registra como error de entrega y **no tumba el
bucle de métricas**.

### Gráficas

Sin `<canvas>` con doble eje Y: mezclar porcentajes y grados en la misma gráfica hace
que la posición relativa de las líneas dependa de cómo escales cada eje, no de los
datos. El histórico agrupa las métricas por unidad y dibuja un grupo cada vez. La
paleta está validada para daltonismo y contraste sobre fondo oscuro, y ningún estado
se comunica solo con color: siempre hay icono o texto al lado.

---

## Seguridad

- Contraseña hasheada con **Argon2id**; sesión en **JWT dentro de una cookie httpOnly**,
  inaccesible desde JavaScript. El hash se verifica siempre, aunque el usuario no exista,
  para no delatar por tiempo cuál es el correcto.
- **Cerrar sesión invalida el token en el servidor**, no solo borra la cookie: una copia
  robada deja de servir en el acto.
- Bloqueo temporal por IP tras varios intentos fallidos (`SM_LOGIN_MAX_ATTEMPTS`).
- **Cabecera `Host` validada** contra *DNS rebinding*. Sin esto, una web maliciosa abierta
  desde cualquier equipo de tu red puede hacer que su dominio pase a resolver a la IP de la
  Pi y hablar con el panel como si fuera mismo origen, con tu cookie incluida. El ataque
  necesita un dominio, así que por defecto se aceptan IP, `localhost` y nombres
  `.local`/`.lan`/`.home`/`.internal`, y se rechaza el resto (`SM_ALLOWED_HOSTS` para añadir).
- **`Origin` validado en el handshake del WebSocket.** Los WebSockets no pasan por CORS:
  sin esta comprobación cualquier web podría abrir uno contra el panel y el navegador
  adjuntaría la cookie de sesión (*cross-site WebSocket hijacking*).
- **CSP con `script-src 'self'`** más `X-Frame-Options`, `nosniff` y `Referrer-Policy`.
  Ningún script va embebido en el HTML, así que un XSS no llegaría a ejecutarse.
- Cookie `SameSite=Lax`: es la protección CSRF del panel, ya que impide que la cookie
  viaje en peticiones POST/DELETE originadas fuera del sitio.
- `/health` es el único endpoint público, y no expone ninguna métrica del sistema.
- Terminación de procesos: nunca PID ≤ 1, nunca el propio monitor, nunca los de
  `SM_PROTECTED_PROCESSES`, y por defecto solo los del usuario de la app. Cada intento,
  permitido o rechazado, queda en la tabla `audit_log`.
- No se confía en `X-Forwarded-For`: sin proxy delante, cualquiera podría falsearla
  para saltarse el bloqueo por intentos.

**Dos límites que conviene tener presentes:**

1. **HTTP plano manda la contraseña en claro.** Para una LAN doméstica suele ser
   aceptable; si algún día lo expones más allá, pon Caddy o nginx con TLS delante y
   pon `SM_COOKIE_SECURE=true`.
2. **Sin privilegios no se ven los sockets ajenos.** El contenedor corre como usuario
   normal con `cap_drop: ALL`, así que la tabla de conexiones no puede atribuir a su
   proceso los sockets de otros usuarios; la interfaz lo avisa. Descomenta
   `cap_add: [SYS_PTRACE]` en el compose si prefieres verlo todo.

### "Top procesos por consumo de red"

Linux **no expone bytes de red por proceso**: `/proc/<pid>/net/dev` pertenece al
*namespace* de red, no al proceso, así que todos los procesos del mismo namespace ven
los mismos contadores. Medir bytes reales por proceso exige `nethogs` (con `NET_ADMIN`
y `NET_RAW`) o eBPF. Lo que sí es barato y responde a la pregunta útil —quién está
hablando con el exterior— es agrupar las conexiones abiertas por proceso, que es lo
que hace la tabla del panel de Red.

---

## Configuración

Todas las opciones son variables de entorno con prefijo `SM_`; están documentadas
una a una en [.env.example](.env.example). Las más relevantes:

| Variable | Por defecto | Para qué |
|---|---|---|
| `SM_USERNAME` / `SM_PASSWORD` | `admin` / — | Credenciales. Mejor `SM_PASSWORD_HASH`. |
| `SM_PORT` | `7000` | Puerto de escucha. Lo pregunta `docker-up.sh` al instalar. |
| `SM_FAST_INTERVAL` | `2.0` | Cadencia de las métricas en vivo. |
| `SM_SLOW_INTERVAL` | `6.0` | Cadencia de procesos, discos y conexiones. |
| `SM_RETENTION_DAYS` | `7` | Días de histórico antes de purgar. |
| `SM_ALLOW_KILL` | `true` | Permite terminar procesos desde la interfaz. |
| `SM_ALLOW_KILL_FOREIGN` | `false` | Permite terminar procesos de otros usuarios. Se respeta también cuando el monitor corre como root. |
| `SM_COOKIE_SECURE` | `false` | Ponlo a `true` en cuanto haya TLS delante. |
| `SM_ALLOWED_HOSTS` | — | Nombres extra aceptados en la cabecera `Host`. |
| `SM_TELEGRAM_BOT_TOKEN` | — | Con `SM_TELEGRAM_CHAT_ID`, activa el sink de Telegram. |

## API

Todo requiere sesión salvo `/health`.

| Método | Ruta | Qué hace |
|---|---|---|
| `GET` | `/health` | Estado del servicio. 503 si el bucle de muestreo está parado. |
| `POST` | `/api/login` · `/api/logout` | Sesión. |
| `WS` | `/ws` | Métricas en vivo. `{"action":"subscribe","channels":[…]}` |
| `GET` | `/api/metrics/now` · `/live` | Último snapshot · muestreo forzado. |
| `GET` | `/api/metrics/history?minutes=1440` | Serie agregada del histórico. |
| `GET` · `DELETE` | `/api/processes` · `/api/processes/{pid}?force=` | Listar · terminar. |
| `GET` | `/api/network/connections` | Conexiones activas. |
| `GET` `POST` `PUT` `DELETE` | `/api/alerts/rules[/{id}]` | CRUD de umbrales. |
| `POST` | `/api/alerts/test/{sink}` | Envía una notificación de prueba. |
| `GET` | `/api/alerts/events` · `/api/alerts/audit` | Disparos · registro de auditoría. |

## Desarrollo

Requiere **Python 3.11 o superior** (la imagen Docker va con 3.12).

```bash
pip install -r requirements-dev.txt
cp .env.example .env
python -m app.metrics.dump --watch   # los colectores, sin servidor de por medio
python -m app.main                   # servidor en http://localhost:7000
python -m pytest                     # 73 tests
ruff check app tests                 # mismo linter que en CI
```

CI ejecuta los tests en Python 3.11/3.12/3.13, construye la imagen para amd64 y
arm64, y arranca el contenedor sobre Linux real para comprobar `/health` y que los
colectores ven RAM y particiones.

`python -m app.metrics.dump` es la herramienta para contrastar los números contra
`htop`, `free -h` y `df -h` sin meter web, WebSockets y base de datos por medio.

## Estructura

```
app/
├── main.py            arranque, lifespan, montaje de rutas
├── config.py          configuración (variables SM_*)
├── metrics/           colectores puros: no importan api/, storage/ ni alerts/
├── core/              scheduler (los tres bucles), hub de WebSockets, seguridad
│                     y endurecimiento HTTP (Host, CSP, cabeceras)
├── storage/           SQLite, agregación por minuto, retención
├── alerts/            motor de umbrales y sinks de notificación
├── api/               rutas HTTP y endpoint WebSocket
├── templates/         login y dashboard (Jinja2)
└── static/            CSS, módulos ES y Chart.js vendorizado

docker-up.sh           primer arranque: .env, credenciales, comprobaciones
docker-update.sh       actualización con copia previa y vuelta atrás
```

La regla que mantiene esto ordenado: **`metrics/` no importa nada del resto**.
Devuelve diccionarios y ya está, lo que permite probar los colectores sin levantar
el servidor.
