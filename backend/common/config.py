"""
Módulo de configuración centralizada y fuertemente tipada para el backend
del Observatorio de Actividad Sísmica.

Lee las variables de entorno definidas en .env y el sistema operativo,
proporcionando validación, valores por defecto seguros y métodos de conveniencia
para PostgreSQL, Apache Kafka, USGS y FastAPI.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote_plus

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Localizar la raíz del proyecto (directorio que contiene compose.yaml o .env)
_CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _CURRENT_DIR.parent.parent

# Cargar variables de entorno desde el archivo .env si existe
_env_file = PROJECT_ROOT / ".env"
if _env_file.exists():
    load_dotenv(dotenv_path=_env_file, override=False)
else:
    load_dotenv(override=False)


class PostgresConfig(BaseModel):
    """
    Configuración de conexión para PostgreSQL 16.
    """
    host: str = Field(default_factory=lambda: os.getenv("POSTGRES_HOST", "postgres"))
    port: int = Field(default_factory=lambda: int(os.getenv("POSTGRES_PORT", "5432")))
    user: str = Field(default_factory=lambda: os.getenv("POSTGRES_USER", "sismo"))
    password: str = Field(default_factory=lambda: os.getenv("POSTGRES_PASSWORD", "sismo_secreto"))
    database: str = Field(default_factory=lambda: os.getenv("POSTGRES_DB", "sismos"))

    @property
    def dsn(self) -> str:
        """
        Retorna la cadena DSN estándar de conexión PostgreSQL (URI RFC 3986).
        """
        user_enc = quote_plus(self.user)
        pass_enc = quote_plus(self.password)
        return f"postgresql://{user_enc}:{pass_enc}@{self.host}:{self.port}/{self.database}"

    @property
    def connection_params(self) -> Dict[str, Any]:
        """
        Retorna los parámetros en formato diccionario para psycopg / asyncpg.
        """
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "dbname": self.database,
        }


class KafkaConfig(BaseModel):
    """
    Configuración de mensajería para Apache Kafka en modo KRaft.
    """
    bootstrap_servers: str = Field(
        default_factory=lambda: os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    )
    topic: str = Field(
        default_factory=lambda: os.getenv("KAFKA_TOPIC", "terremotos")
    )
    topic_replay: str = Field(
        default_factory=lambda: os.getenv("KAFKA_TOPIC_REPLAY", "terremotos-replay")
    )
    consumer_group: str = Field(
        default_factory=lambda: os.getenv("KAFKA_CONSUMER_GROUP", "observatorio-consumidor")
    )

    @property
    def producer_params(self) -> Dict[str, Any]:
        """
        Parámetros recomendados para inicializar AIOKafkaProducer.
        """
        return {
            "bootstrap_servers": self.bootstrap_servers,
            "acks": "all",
            "enable_idempotence": True,
            "client_id": "sismos-producer-client",
        }

    @property
    def consumer_params(self) -> Dict[str, Any]:
        """
        Parámetros recomendados para inicializar AIOKafkaConsumer.
        """
        return {
            "bootstrap_servers": self.bootstrap_servers,
            "group_id": self.consumer_group,
            "auto_offset_reset": "earliest",
            "enable_auto_commit": False,
        }


class USGSConfig(BaseModel):
    """
    Configuración para la extracción de datos desde la API del USGS.
    """
    feed_url: str = Field(
        default_factory=lambda: os.getenv(
            "USGS_FEED_URL",
            "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson",
        )
    )
    poll_interval_seconds: int = Field(
        default_factory=lambda: int(os.getenv("USGS_POLL_INTERVAL_SECONDS", "60"))
    )
    query_url: str = "https://earthquake.usgs.gov/fdsnws/event/1/query"
    timeout_seconds: float = 30.0
    max_retries: int = 4
    backoff_factor: float = 2.0


class ApiConfig(BaseModel):
    """
    Configuración del servicio FastAPI y CORS.
    """
    host: str = Field(default_factory=lambda: os.getenv("API_HOST", "0.0.0.0"))
    port: int = Field(default_factory=lambda: int(os.getenv("API_PORT", "8000")))
    cors_origins_raw: str = Field(
        default_factory=lambda: os.getenv(
            "CORS_ORIGINS",
            "http://localhost:4200,http://127.0.0.1:4200,https://*.netlify.app",
        )
    )

    @property
    def cors_origins(self) -> List[str]:
        """
        Retorna la lista de orígenes CORS parseada y sin espacios en blanco.
        """
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]


class ProducerConfig(BaseModel):
    """
    Configuración específica de persistencia y ejecución del Productor.
    """
    state_file: Path = Field(
        default_factory=lambda: Path(
            os.getenv("PRODUCER_STATE_FILE", str(PROJECT_ROOT / "data" / "estado_productor.json"))
        )
    )
    # Límite de eventos retenidos en memoria para evitar crecimiento desmedido en ejecuciones de meses
    max_state_entries: int = 25000


class Settings(BaseModel):
    """
    Contenedor principal de configuración unificada del sistema.
    """
    postgres: PostgresConfig = Field(default_factory=PostgresConfig)
    kafka: KafkaConfig = Field(default_factory=KafkaConfig)
    usgs: USGSConfig = Field(default_factory=USGSConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    producer: ProducerConfig = Field(default_factory=ProducerConfig)
    project_root: Path = PROJECT_ROOT


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Devuelve la instancia singleton en caché de la configuración del sistema.
    """
    return Settings()
