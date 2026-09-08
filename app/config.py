"""Configuracion central. Todo se lee de variables de entorno con prefijo SM_."""
from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SM_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Autenticacion
    username: str = "admin"
    password: str = ""
    password_hash: str = ""
    secret_key: str = ""
    session_hours: int = 12
    login_max_attempts: int = 8
    login_lockout_seconds: int = 300

    # Servidor
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"

    # Cadencias
    fast_interval: float = 2.0
    slow_interval: float = 6.0
    persist_interval: float = 60.0

    # Historico
    db_path: Path = Path("data/history.db")
    retention_days: int = 7

    # Acceso al host
    host_root: str = "/"
    sys_path: str = "/sys"
    extra_mounts: str = ""
    procfs_path: str = ""

    # Operaciones sensibles
    allow_kill: bool = True
    allow_kill_foreign: bool = False
    protected_processes: str = "systemd,init,sshd,dockerd,containerd"

    # Sinks de alertas
    alert_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook_url: str = ""

    @field_validator("fast_interval", "slow_interval", "persist_interval")
    @classmethod
    def _min_interval(cls, v: float) -> float:
        # Por debajo de 0.5s el propio muestreo se convierte en la carga dominante.
        return max(0.5, v)

    @property
    def db_file(self) -> Path:
        p = self.db_path
        return p if p.is_absolute() else PROJECT_DIR / p

    @property
    def protected_list(self) -> set[str]:
        return {p.strip().lower() for p in self.protected_processes.split(",") if p.strip()}

    @property
    def extra_mount_list(self) -> list[str]:
        return [m.strip() for m in self.extra_mounts.split(",") if m.strip()]

    def resolve_secret(self) -> str:
        """Devuelve la clave JWT, generandola y persistiendola la primera vez.

        Si se regenerase en cada arranque, todas las sesiones caducarian al
        reiniciar el contenedor.
        """
        if self.secret_key:
            return self.secret_key
        key_file = self.db_file.parent / ".secret_key"
        key_file.parent.mkdir(parents=True, exist_ok=True)
        if key_file.exists():
            existing = key_file.read_text().strip()
            if existing:
                return existing
        generated = secrets.token_urlsafe(48)
        key_file.write_text(generated)
        try:
            key_file.chmod(0o600)
        except OSError:
            pass
        return generated


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
