#!/usr/bin/env sh
# Levanta el panel listo para usarse desde cualquier dispositivo de la LAN.
#
# Se encarga de lo que hay que hacer antes de "docker compose up":
#   1. Crear .env (a partir de .env.example) si aún no existe.
#   2. Generar SM_SECRET_KEY y, en el primer arranque, las credenciales.
#   3. Comprobar que el host puede dar lo que el compose pide: Linux de verdad
#      (pid/network host), el puerto libre, y /sys para la temperatura.
#   4. Leer SM_PORT del .env y usarlo para esperar al arranque y anunciar la URL.
#   5. Esperar al healthcheck y verificar que el login funciona de verdad.
#
# Uso: ./docker-up.sh [args extra para docker compose up]
set -e
cd "$(dirname "$0")"

COMPOSE="deploy/docker-compose.yml"
SERVICIO="systemmonitor"

aviso() { printf '\n\033[33m%s\033[0m\n' "$*" >&2; }
error() { printf '\n\033[31m%s\033[0m\n' "$*" >&2; }
paso()  { printf '\n\033[36m── %s\033[0m\n' "$*"; }

# ── Comprobaciones del entorno ────────────────────────────────────────────────

# Este script escribe .env en este directorio. Ejecutarlo con sudo lo dejaría
# como root y el siguiente arranque normal fallaría al crear .env.tmp. Docker no
# necesita sudo cuando el usuario pertenece al grupo docker.
if [ "$(id -u)" -eq 0 ]; then
    error "no ejecutes docker-up.sh con sudo."
    echo "       Haría que .env quedase propiedad de root." >&2
    echo "       Ejecútalo como tu usuario normal: ./docker-up.sh" >&2
    exit 1
fi

PRUEBA=".docker-up-permission-test.$$"
if ! (umask 077 && : > "$PRUEBA") 2>/dev/null; then
    error "no se puede escribir en $(pwd)."
    echo "       El directorio puede estar montado como solo lectura, o tener" >&2
    echo "       permisos que impiden escribir al usuario $(id -un)." >&2
    echo "       Si antes se ejecutó con sudo, repáralo con:" >&2
    echo "       sudo chown -R \"$(id -un):$(id -gn)\" \"$(pwd)\"" >&2
    exit 1
fi
rm -f "$PRUEBA"

if [ -e .env ] && { [ ! -r .env ] || [ ! -w .env ]; }; then
    error "no tienes permiso para leer o actualizar .env."
    echo "       sudo chown \"$(id -un):$(id -gn)\" .env" >&2
    exit 1
fi

# Errores accionables antes de tocar .env o empezar una construcción larga.
if ! command -v docker >/dev/null 2>&1; then
    error "no se ha encontrado Docker en el PATH."
    echo "       En Ubuntu Server: https://docs.docker.com/engine/install/ubuntu/" >&2
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    error "Docker no está disponible."
    echo "       Comprueba que el daemon está arrancado y que tu usuario está en" >&2
    echo "       el grupo docker:  sudo usermod -aG docker \"$(id -un)\"" >&2
    echo "       (hay que volver a iniciar sesión para que surta efecto)." >&2
    exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
    error "falta Docker Compose v2 (el comando 'docker compose')."
    exit 1
fi

# El compose usa "pid: host" y "network_mode: host". En Docker Desktop
# (Windows/macOS) el contenedor corre dentro de una VM Linux, así que esos dos
# ajustes darían los procesos y las interfaces de la VM, no los de tu máquina:
# el panel arrancaría y mostraría datos, pero de un sistema que no es el tuyo.
if [ "$(uname -s)" != "Linux" ]; then
    aviso "AVISO: esto no es Linux ($(uname -s))."
    echo "       Con Docker Desktop, 'pid: host' y 'network_mode: host' se refieren" >&2
    echo "       a la VM de Docker, no a tu equipo: verías los procesos y la red de" >&2
    echo "       esa VM. Para desarrollar, ejecuta la app directamente:" >&2
    echo "           pip install -r requirements.txt && python -m app.main" >&2
    printf '\n¿Continuar de todos modos? [s/N]: ' >&2
    if [ -t 0 ]; then
        read -r RESPUESTA
        case "$RESPUESTA" in
            s|S|si|SI|Si|y|Y) ;;
            *) echo "Cancelado." >&2; exit 1 ;;
        esac
    else
        echo "No hay terminal interactiva; se cancela." >&2
        exit 1
    fi
fi

# ── Intérprete Python ─────────────────────────────────────────────────────────
# Solo para generar SM_SECRET_KEY. El hash de la contraseña NO se genera aquí:
# se hace dentro de la imagen ya construida, para que use exactamente los mismos
# parámetros de Argon2 que el login.
if command -v python3 >/dev/null 2>&1; then
    PY_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PY_CMD="python"
else
    PY_CMD=""
fi

# ── Utilidades sobre .env ─────────────────────────────────────────────────────
env_get() {
    # Valor de una clave en .env (vacío si no está o está comentada).
    [ -f .env ] || return 0
    sed -n "s/^$1=//p" .env | head -n 1
}

env_set() {
    # Sustituye la clave si existe, la añade al final si no. Se escribe en un
    # temporal y se renombra para no dejar el .env a medias si algo falla.
    #
    # Los valores NO se escapan. Aquí no hace falta, al contrario que en otros
    # proyectos: el compose vive en deploy/, así que el fichero de
    # interpolación de Compose sería deploy/.env, no este. Este .env llega al
    # contenedor por "env_file:", que pasa los valores literales. Por eso el
    # hash de Argon2, que lleva varios '$', viaja intacto. Aun así el arranque
    # verifica el login al final: si esto cambiase, se vería al momento.
    #
    # El valor se pasa a awk por el entorno, no con -v: awk interpreta las
    # secuencias de escape en los valores de -v, así que un valor con una
    # barra invertida llegaría transformado.
    if grep -q "^$1=" .env; then
        SM_ENV_VALOR="$2" awk -v k="$1" '
            BEGIN { FS = OFS = "="; v = ENVIRON["SM_ENV_VALOR"] }
            $1 == k { print k "=" v; next }
            { print }' .env > .env.tmp
        mv .env.tmp .env
    else
        printf '%s=%s\n' "$1" "$2" >> .env
    fi
}

# ── 1. .env ───────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
    cp .env.example .env
    chmod 600 .env 2>/dev/null || true
    echo "Creado .env a partir de .env.example."
fi

# ── 2. SM_SECRET_KEY ──────────────────────────────────────────────────────────
# Firma los tokens de sesión. Cambiarla no destruye nada, pero cierra la sesión
# de todos los navegadores, así que solo se genera cuando falta de verdad.
if [ -z "$(env_get SM_SECRET_KEY)" ]; then
    if [ -n "$PY_CMD" ]; then
        CLAVE=$("$PY_CMD" -c "import secrets; print(secrets.token_urlsafe(48))")
    else
        # head -c de /dev/urandom + base64: disponible en cualquier Ubuntu sin
        # depender de que haya Python instalado en el host.
        CLAVE=$(head -c 36 /dev/urandom | base64 | tr -d '\n=' | tr '+/' '-_')
    fi
    env_set SM_SECRET_KEY "$CLAVE"
    echo "SM_SECRET_KEY generada."
fi

# ── 3. Puerto ─────────────────────────────────────────────────────────────────
PORT=$(env_get SM_PORT)
[ -n "$PORT" ] || PORT=8080

# Con network_mode: host no hay mapeo de puertos: uvicorn se ata directamente al
# puerto del host. Si ya está ocupado, el contenedor no arranca y se queda
# reiniciándose en bucle con "address already in use" enterrado en el log.
puerto_ocupado() {
    if command -v ss >/dev/null 2>&1; then
        ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$PORT\$"
    elif command -v netstat >/dev/null 2>&1; then
        netstat -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$PORT\$"
    else
        return 1
    fi
}

# El propio panel ya en marcha no cuenta: este script también sirve para
# reiniciarlo tras cambiar el .env.
YA_EN_MARCHA=$(docker compose -f "$COMPOSE" ps -q "$SERVICIO" 2>/dev/null || true)
if [ -z "$YA_EN_MARCHA" ] && puerto_ocupado; then
    error "el puerto $PORT ya está ocupado en este equipo."
    echo "       Con network_mode: host no hay mapeo que valga: la aplicación se" >&2
    echo "       ata directamente a ese puerto y no arrancaría." >&2
    echo "       Mira quién lo tiene:  sudo ss -ltnp | grep :$PORT" >&2
    echo "       O elige otro:         cambia SM_PORT en .env" >&2
    exit 1
fi

# ── 4. Temperatura ────────────────────────────────────────────────────────────
# Aviso, no error: el panel funciona sin sensor, pero conviene saberlo ahora y
# no buscando después por qué la tarjeta de temperatura sale vacía.
if [ ! -d /sys/class/thermal ]; then
    aviso "AVISO: no existe /sys/class/thermal en este equipo."
    echo "       La tarjeta de temperatura aparecerá como 'sensor no disponible'." >&2
    echo "       En una Raspberry Pi con Ubuntu Server debería existir." >&2
fi

# ── 5. Construir ──────────────────────────────────────────────────────────────
# Se construye ANTES de pedir la contraseña porque el hash se genera con la
# imagen recién construida.
SM_VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' app/version.py | head -n 1)
[ -n "$SM_VERSION" ] || SM_VERSION=latest
export SM_VERSION

paso "Construyendo la imagen $SM_VERSION"
docker compose -f "$COMPOSE" build

# ── 6. Credenciales ───────────────────────────────────────────────────────────
# Sin ellas la aplicación se niega a arrancar, así que se piden en el primer uso.
# .env.example trae SM_PASSWORD=cambiame, que cuenta como "sin configurar": si se
# aceptara, el panel quedaría abierto con una contraseña conocida.
PASSWORD_ACTUAL=$(env_get SM_PASSWORD)
HASH_ACTUAL=$(env_get SM_PASSWORD_HASH)

necesita_credenciales=0
[ -z "$HASH_ACTUAL" ] && necesita_credenciales=1
[ "$PASSWORD_ACTUAL" = "cambiame" ] && [ -z "$HASH_ACTUAL" ] && necesita_credenciales=1

if [ "$necesita_credenciales" -eq 1 ]; then
    if [ ! -t 0 ]; then
        error "no hay credenciales y no hay terminal interactiva."
        echo "       Ejecuta ./docker-up.sh desde una terminal, o genera el hash a mano:" >&2
        echo "           docker run --rm -i systemmonitor:$SM_VERSION \\" >&2
        echo "               python -m app.tools.hashpw --stdin" >&2
        exit 1
    fi

    paso "Credenciales de acceso (primer arranque)"
    printf 'Usuario [admin]: '
    read -r USUARIO
    [ -n "$USUARIO" ] || USUARIO="admin"

    stty -echo 2>/dev/null || true
    printf 'Contraseña: '
    read -r PW
    printf '\nRepite la contraseña: '
    read -r PW2
    stty echo 2>/dev/null || true
    printf '\n'

    if [ -z "$PW" ] || [ "$PW" != "$PW2" ]; then
        error "las contraseñas no coinciden (o está vacía). No se ha configurado nada."
        exit 1
    fi

    # El hash se genera DENTRO de la imagen: mismos parámetros de Argon2 que
    # usará el login. Si se calculara con un Python del host, bastaría una
    # versión distinta de argon2-cffi para que el coste no fuese el previsto.
    # La contraseña va por stdin, nunca como argumento: los argumentos son
    # visibles en la lista de procesos del equipo.
    HASH=$(printf '%s\n' "$PW" | docker run --rm -i \
        "systemmonitor:$SM_VERSION" python -m app.tools.hashpw --stdin)
    PW=""; PW2=""
    unset PW PW2

    if [ -z "$HASH" ]; then
        error "no se pudo generar el hash de la contraseña."
        exit 1
    fi

    env_set SM_USERNAME "$USUARIO"
    env_set SM_PASSWORD_HASH "$HASH"
    # Se vacía la contraseña en claro que venía del ejemplo. La aplicación
    # prefiere el hash, pero dejar 'cambiame' escrito invita a reactivarla.
    env_set SM_PASSWORD ""
    chmod 600 .env 2>/dev/null || true
    echo "Credenciales guardadas en .env (hash Argon2, la contraseña no se guarda)."
    CREDENCIALES_NUEVAS=1
fi

# ── 7. Arranque ───────────────────────────────────────────────────────────────
paso "Levantando"
docker compose -f "$COMPOSE" up -d "$@"

# "up -d" termina cuando crea el contenedor, no cuando la aplicación responde.
# /health devuelve 503 si el bucle de muestreo se ha parado, así que esperar
# aquí distingue "el contenedor está arriba" de "el monitor funciona".
CONTENEDOR=$(docker compose -f "$COMPOSE" ps -q "$SERVICIO")
if [ -z "$CONTENEDOR" ]; then
    error "Docker Compose no creó el contenedor $SERVICIO."
    docker compose -f "$COMPOSE" logs --tail=100 "$SERVICIO" >&2 || true
    exit 1
fi

paso "Esperando a que responda"
INTENTOS=30
sano=0
while [ "$INTENTOS" -gt 0 ]; do
    ESTADO=$(docker inspect --format '{{.State.Status}}' "$CONTENEDOR" 2>/dev/null || echo ausente)
    case "$ESTADO" in
        exited|dead)
            error "el contenedor se ha parado (estado: $ESTADO)."
            docker compose -f "$COMPOSE" logs --tail=100 "$SERVICIO" >&2 || true
            exit 1
            ;;
    esac
    if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
        sano=1
        break
    fi
    INTENTOS=$((INTENTOS - 1))
    printf '.'
    sleep 2
done
printf '\n'

if [ "$sano" -eq 0 ]; then
    error "la aplicación no responde en http://127.0.0.1:$PORT/health"
    docker compose -f "$COMPOSE" logs --tail=100 "$SERVICIO" >&2 || true
    exit 1
fi

# ── 8. Verificar que se puede entrar ──────────────────────────────────────────
# /health responde sin autenticación, así que un panel al que nadie puede entrar
# lo daría por sano. Con las credenciales recién puestas se comprueba de verdad:
# es lo que detectaría que el hash no llegó intacto al contenedor.
if [ "${CREDENCIALES_NUEVAS:-0}" -eq 1 ]; then
    USUARIO_ENV=$(env_get SM_USERNAME)
    # Contraseña incorrecta a propósito: un 401 demuestra que el hash se leyó y
    # se comparó. Un 500 significaría que el contenedor no tiene credenciales
    # válidas. Así se comprueba sin volver a pedirle la contraseña al usuario ni
    # dejarla escrita en ningún sitio.
    CODIGO=$(curl -s -o /dev/null -w '%{http_code}' \
        -X POST "http://127.0.0.1:$PORT/api/login" \
        -H 'Content-Type: application/json' \
        -d "{\"username\":\"$USUARIO_ENV\",\"password\":\"x\"}" 2>/dev/null || echo 000)
    if [ "$CODIGO" != "401" ]; then
        aviso "AVISO: la comprobación del login devolvió $CODIGO en vez de 401."
        echo "       Se esperaba un rechazo limpio de una contraseña incorrecta." >&2
        echo "       Puede que SM_PASSWORD_HASH no haya llegado intacto al contenedor." >&2
        echo "       Revisa:  docker compose -f $COMPOSE exec $SERVICIO env | grep SM_PASSWORD_HASH" >&2
    fi
fi

# ── 9. Dirección en la LAN ────────────────────────────────────────────────────
# Se calcula en el host: con network_mode host la aplicación comparte la red,
# pero sigue sin saber por cuál de las direcciones la alcanzan los demás.
LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -n "$LAN_IP" ] || LAN_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}')
[ -n "$LAN_IP" ] || LAN_IP="<IP_DEL_SERVIDOR>"

echo
echo "SystemMonitor $SM_VERSION levantado:"
echo "  Este equipo : http://localhost:$PORT"
echo "  Red local   : http://$LAN_IP:$PORT"
echo "  Usuario     : $(env_get SM_USERNAME)"
echo
echo "Va por HTTP: la contraseña y la cookie de sesión viajan en claro por tu red."
echo "Para una LAN doméstica suele bastar; si lo expones más allá, pon un proxy con"
echo "TLS delante y añade SM_COOKIE_SECURE=true al .env."
echo
echo "Entra por IP. Los nombres de dominio externos se rechazan a propósito (DNS"
echo "rebinding); si usas un nombre propio, añádelo a SM_ALLOWED_HOSTS en .env."
echo
echo "Registro en vivo : docker compose -f $COMPOSE logs -f"
echo "Actualizar       : ./docker-update.sh"
