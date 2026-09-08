-- Muestras agregadas por minuto. A 1 fila/minuto son 1440 filas por dia:
-- una semana de historico ocupa alrededor de 1 MB.
CREATE TABLE IF NOT EXISTS samples (
    ts          INTEGER PRIMARY KEY,   -- epoch en segundos, alineado al minuto
    cpu_pct     REAL,
    cpu_peak    REAL,                  -- pico dentro del minuto: los picos cortos
                                       -- desaparecerian al promediar
    temp_c      REAL,
    freq_mhz    REAL,
    mem_pct     REAL,
    mem_used    INTEGER,
    mem_total   INTEGER,
    swap_pct    REAL,
    net_rx      REAL,                  -- bytes/s medios en el minuto
    net_tx      REAL,
    disk_pct    REAL,                  -- particion raiz
    load1       REAL
);

CREATE TABLE IF NOT EXISTS alert_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    metric      TEXT    NOT NULL,      -- cpu | memory | swap | disk | temperature | load
    target      TEXT    NOT NULL DEFAULT '',  -- punto de montaje si metric=disk
    operator    TEXT    NOT NULL DEFAULT 'gt',
    threshold   REAL    NOT NULL,
    duration_s  INTEGER NOT NULL DEFAULT 60,   -- debe mantenerse este tiempo
    cooldown_s  INTEGER NOT NULL DEFAULT 900,  -- silencio entre disparos
    sinks       TEXT    NOT NULL DEFAULT 'log',
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS alert_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,
    rule_id     INTEGER,
    rule_name   TEXT,
    metric      TEXT,
    target      TEXT,
    value       REAL,
    threshold   REAL,
    state       TEXT,                  -- firing | resolved
    delivery    TEXT                   -- resultado por sink, en JSON
);
CREATE INDEX IF NOT EXISTS idx_alert_events_ts ON alert_events(ts DESC);

-- Rastro de las acciones sensibles: quien mato que y desde donde.
CREATE TABLE IF NOT EXISTS audit_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       INTEGER NOT NULL,
    username TEXT,
    ip       TEXT,
    action   TEXT,
    detail   TEXT,
    ok       INTEGER
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts DESC);
