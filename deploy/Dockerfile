# Dos etapas: las dependencias se compilan en la primera y a la imagen final
# solo pasa el virtualenv. En una Pi eso son ~120 MB en vez de ~450 MB, y sin
# compiladores dentro del contenedor que corre en tu red.
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# argon2-cffi y psutil traen ruedas para arm64, pero no siempre para armv7
# (Pi de 32 bits): con estas herramientas se compilan si hace falta.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SM_HOST=0.0.0.0 \
    SM_PORT=7000 \
    SM_DB_PATH=/data/history.db \
    SM_HOST_ROOT=/host/root \
    SM_SYS_PATH=/host/sys

COPY --from=builder /opt/venv /opt/venv

# Usuario sin privilegios. Con este UID el kill queda limitado a los procesos
# del propio usuario, que es la restriccion que se quiere por defecto.
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin monitor \
    && mkdir -p /data /host/root /host/sys \
    && chown monitor:monitor /data

WORKDIR /srv
COPY --chown=monitor:monitor app ./app

USER monitor
EXPOSE 7000
VOLUME ["/data"]

# Sin curl en la imagen: urllib ya viene con Python y evita 10 MB de paquete.
# El endpoint devuelve 503 si el bucle de muestreo se ha parado, asi que esto
# detecta un monitor "vivo pero roto", no solo un proceso caido.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request,sys; \
url=f\"http://127.0.0.1:{os.environ.get('SM_PORT','7000')}/health\"; \
sys.exit(0 if urllib.request.urlopen(url, timeout=4).status == 200 else 1)"

# Un solo worker a proposito: los colectores guardan la lectura anterior para
# calcular tasas, y varios procesos multiplicarian el muestreo sin ganancia.
# Se arranca por el modulo, no por uvicorn directamente, para que respete
# SM_HOST / SM_PORT / SM_LOG_LEVEL sin duplicar los valores aqui.
CMD ["python", "-m", "app.main"]
