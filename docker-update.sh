#!/usr/bin/env sh
# Actualiza la instalación en marcha y la deja comprobada.
#
# Actualizar a mano era `git pull && ./docker-up.sh`, con cuatro cosas que solo
# se descubren tarde:
#
#   1. Nada verificaba que la versión nueva arrancase. Con
#      `restart: unless-stopped` el contenedor se queda reiniciándose en bucle
#      y te enteras al abrir el panel. Aquí se espera a que `/health` responda,
#      que además devuelve 503 si el bucle de muestreo está parado.
#   2. `docker compose build` sin etiquetar deja solo la imagen nueva, así que
#      volver atrás era reconstruir desde el código anterior. Ahora cada versión
#      queda etiquetada y la vuelta atrás es inmediata.
#   3. El histórico y las reglas de alerta viven en un volumen de Docker. Antes
#      de tocar nada se saca una copia consistente (SQLite en modo WAL no se
#      puede copiar con `cp` mientras se escribe).
#   4. Este script se actualiza a sí mismo. El `git pull` reemplaza el fichero
#      que el intérprete está leyendo, y `sh` guarda un desplazamiento dentro de
#      él: si el fichero nuevo tiene otro tamaño, lo que queda por leer se
#      descoloca y la actualización muere con un error de sintaxis absurdo. Por
#      eso lo primero que hace es reejecutarse desde una copia.
#
# Si la versión nueva no responde, se vuelve sola a la imagen anterior.
#
# Uso: ./docker-update.sh [--sin-pull]
set -e

# El directorio del proyecto se fija antes que nada: la copia de la que se
# reejecuta vive en /tmp, así que allí `dirname "$0"` ya no sirve.
SM_PROYECTO="${SM_PROYECTO:-$(cd "$(dirname "$0")" && pwd)}"
export SM_PROYECTO
cd "$SM_PROYECTO"

# Reejecutarse desde una copia: lo que corre es una foto del script y el pull
# puede reemplazar el original sin descolocar esta ejecución. Si la copia no se
# pudiera crear se sigue igualmente: es una protección, no un requisito.
if [ -z "$SM_UPDATE_COPIA" ]; then
    copia=$(mktemp "${TMPDIR:-/tmp}/sm-update.XXXXXX" 2>/dev/null) || copia=""
    if [ -n "$copia" ] && cp "$0" "$copia" 2>/dev/null; then
        SM_UPDATE_COPIA="$copia"
        export SM_UPDATE_COPIA
        codigo=0
        sh "$copia" "$@" || codigo=$?
        rm -f "$copia"
        exit "$codigo"
    fi
fi

COMPOSE="deploy/docker-compose.yml"
SERVICIO="systemmonitor"
ESPERA_SALUD=90   # segundos que se le dan a la versión nueva para responder

SIN_PULL=0
[ "$1" = "--sin-pull" ] && SIN_PULL=1

aviso() { printf '\n\033[33m%s\033[0m\n' "$*" >&2; }
error() { printf '\n\033[31m%s\033[0m\n' "$*" >&2; }
paso()  { printf '\n\033[36m── %s\033[0m\n' "$*"; }

# Con sudo, el git pull deja los ficheros como root y el siguiente ./docker-up.sh
# falla al escribir .env. Docker no necesita sudo si el usuario está en el grupo.
if [ "$(id -u)" -eq 0 ]; then
    error "no ejecutes docker-update.sh con sudo."
    echo "       Ejecútalo como tu usuario normal: ./docker-update.sh" >&2
    exit 1
fi

version_del_codigo() {
    sed -n 's/^__version__ = "\(.*\)"/\1/p' app/version.py | head -n 1
}

# ── 1. Comprobaciones previas ─────────────────────────────────────────────────
paso "Comprobando el estado local"

if [ ! -f .env ]; then
    error "no hay .env. Esto es una instalación nueva: usa ./docker-up.sh."
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    error "Docker no está disponible."
    exit 1
fi

# El .env no se versiona, así que el pull no lo toca. Lo que sí choca son los
# cambios locales en ficheros versionados: se avisa antes de empezar, no a
# mitad de una actualización.
if [ "$SIN_PULL" -eq 0 ] && ! git diff --quiet 2>/dev/null; then
    error "hay cambios locales sin confirmar y el pull chocaría con ellos."
    echo >&2
    echo "  La configuración de esta instalación va en .env, que no se versiona" >&2
    echo "  y sobrevive a las actualizaciones. Si has editado ficheros del" >&2
    echo "  repositorio, decide qué hacer con ellos:" >&2
    echo >&2
    echo "      Ver qué has cambiado:   git diff" >&2
    echo "      Descartarlo:            git checkout -- ." >&2
    echo "      Guardarlo aparte:       git stash" >&2
    echo >&2
    echo "  O actualiza sin traer código nuevo:  ./docker-update.sh --sin-pull" >&2
    exit 1
fi

VERSION_ANTERIOR=$(version_del_codigo)
[ -n "$VERSION_ANTERIOR" ] || VERSION_ANTERIOR="desconocida"
echo "Versión instalada: $VERSION_ANTERIOR"

PORT=$(sed -n 's/^SM_PORT=//p' .env | head -n 1)
[ -n "$PORT" ] || PORT=7000

# ── 2. Copia del histórico ────────────────────────────────────────────────────
# SQLite en modo WAL no se puede copiar con `cp` mientras la aplicación escribe:
# saldría un fichero a medias. La API de backup de sqlite3 sí hace una copia
# consistente en caliente, y el módulo viene con Python, que ya está en la
# imagen. Se guarda el histórico, pero sobre todo las reglas de alerta, que las
# has configurado tú y no se pueden reconstruir.
if [ -n "$(docker compose -f "$COMPOSE" ps -q "$SERVICIO" 2>/dev/null)" ]; then
    paso "Copia de seguridad de la base de datos"
    mkdir -p backups
    MARCA=$(date +%Y%m%d-%H%M%S)
    DESTINO="backups/history_${VERSION_ANTERIOR}_${MARCA}.db"

    if docker compose -f "$COMPOSE" exec -T "$SERVICIO" python -c "
import sqlite3
origen = sqlite3.connect('/data/history.db')
copia = sqlite3.connect('/data/backup-tmp.db')
with copia:
    origen.backup(copia)
copia.close(); origen.close()
" 2>/dev/null && docker compose -f "$COMPOSE" cp \
        "$SERVICIO:/data/backup-tmp.db" "$DESTINO" 2>/dev/null; then
        docker compose -f "$COMPOSE" exec -T "$SERVICIO" \
            rm -f /data/backup-tmp.db 2>/dev/null || true
        echo "Guardada en $DESTINO"
    else
        aviso "AVISO: no se pudo copiar la base de datos; se continúa igualmente."
        echo "       El histórico son métricas recuperables, pero las reglas de" >&2
        echo "       alerta que hayas creado no se podrían restaurar." >&2
    fi
else
    echo "No hay contenedor en marcha; no hay nada que copiar."
fi

# ── 3. Traer los cambios ──────────────────────────────────────────────────────
if [ "$SIN_PULL" -eq 0 ]; then
    paso "Descargando la versión nueva"
    git pull --ff-only
fi

VERSION_NUEVA=$(version_del_codigo)
[ -n "$VERSION_NUEVA" ] || VERSION_NUEVA="desconocida"

if [ "$VERSION_NUEVA" = "$VERSION_ANTERIOR" ]; then
    aviso "Ya estabas en la $VERSION_NUEVA. Se reconstruye igualmente."
else
    echo "Actualizando: $VERSION_ANTERIOR → $VERSION_NUEVA"
    if [ -f CHANGELOG.md ]; then
        paso "Novedades de la $VERSION_NUEVA"
        awk '/^## \[/{n++} n==1{print} n==2{exit}' CHANGELOG.md
    fi
fi

export SM_VERSION="$VERSION_NUEVA"

# ── 4. Construir y levantar ───────────────────────────────────────────────────
paso "Construyendo la imagen $VERSION_NUEVA"
docker compose -f "$COMPOSE" build

paso "Levantando"
docker compose -f "$COMPOSE" up -d

# ── 5. Comprobar que arranca de verdad ────────────────────────────────────────
# /health devuelve 503 si el bucle de muestreo está parado, así que esperar aquí
# distingue "el contenedor está arriba" de "el monitor funciona".
paso "Esperando a que responda (hasta ${ESPERA_SALUD}s)"

sano=0
i=0
while [ "$i" -lt "$ESPERA_SALUD" ]; do
    if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
        sano=1
        break
    fi
    i=$((i + 1))
    printf '.'
    sleep 1
done
printf '\n'

if [ "$sano" -eq 1 ]; then
    paso "Actualización correcta"
    curl -fsS "http://127.0.0.1:${PORT}/health" || true
    printf '\n\nVersión %s en marcha en el puerto %s.\n' "$VERSION_NUEVA" "$PORT"
    exit 0
fi

# ── 6. Vuelta atrás ───────────────────────────────────────────────────────────
error "la versión $VERSION_NUEVA no responde tras ${ESPERA_SALUD}s. Volviendo atrás."

echo >&2
echo "Últimas líneas del registro:" >&2
docker compose -f "$COMPOSE" logs --tail 40 "$SERVICIO" >&2 2>&1 || true

if [ "$VERSION_ANTERIOR" != "desconocida" ] \
   && docker image inspect "systemmonitor:${VERSION_ANTERIOR}" >/dev/null 2>&1; then
    paso "Levantando de nuevo la $VERSION_ANTERIOR"
    SM_VERSION="$VERSION_ANTERIOR" docker compose -f "$COMPOSE" up -d --no-build
    aviso "Se ha vuelto a la $VERSION_ANTERIOR.
El código del repositorio SÍ está actualizado. Para dejarlo también como estaba:
    git checkout v${VERSION_ANTERIOR}"
else
    error "no hay imagen etiquetada de la $VERSION_ANTERIOR; no se puede volver sola."
    echo "       Reconstruye desde el código anterior:" >&2
    echo "           git checkout v${VERSION_ANTERIOR} && ./docker-up.sh" >&2
fi

cat >&2 <<FIN

  La base de datos no se toca al volver atrás: el esquema se crea con
  CREATE TABLE IF NOT EXISTS y no hay migraciones destructivas. Si aun así
  quieres partir de la copia previa a esta actualización, está en:

      backups/history_${VERSION_ANTERIOR}_*.db

  Para restaurarla, con el contenedor parado:

      docker compose -f $COMPOSE cp <fichero> $SERVICIO:/data/history.db

FIN
exit 1
