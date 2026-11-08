"""
Módulo Consumidor de eventos sísmicos en tiempo real (Kafka -> PostgreSQL).

Responsabilidades:
1. Consumo asíncrono desde topics de Kafka ('terremotos' y 'terremotos-replay')
   utilizando aiokafka con semántica at-least-once (enable_auto_commit=False).
2. Validación rigurosa de calidad en 6 dimensiones:
   - Detección y aislamiento de payloads JSON corruptos o incompletos.
   - Comprobación de rangos espaciales (longitud [-180, 180], latitud [-90, 90]).
   - Aislamiento de eventos no sismológicos (properties.type != 'earthquake').
   - Admisión válida de magnitudes nulas o negativas (microterremotos).
   - Admisión válida de profundidades negativas (sismos sobre el nivel del mar).
   - Conversión precisa de marcas temporales Unix epoch (ms) a TIMESTAMPTZ UTC.
3. Enriquecimiento espacial en memoria mediante SpatialMatcher (Point-in-Polygon
   logarítmico O(log N) con STRtree sobre Natural Earth):
   - Asignación de ADM0_A3 ('country_code').
   - Sismos en aguas abiertas tratados limpiamente como NULL / Sin país asignado.
4. Persistencia transaccional e idempotente en PostgreSQL 16:
   - Registro inmutable de la carga útil original en 'eventos_raw' para trazabilidad.
   - Inserción y versionado atómico en 'eventos' y 'eventos_versiones' mediante
     'fn_ingestar_evento':
     * Sismo nuevo -> INSERT en 'eventos' y versión 1 en 'eventos_versiones'.
     * Revisión más reciente -> UPDATE en 'eventos' y versión N+1 en 'eventos_versiones'.
     * Duplicado o versión antigua -> Ignorado silenciosamente (idempotente).
5. Aislamiento de anomalías en 'eventos_cuarentena' con diagnóstico técnico.
6. Tolerancia a fallos, reintentos con pool de conexiones y cierre ordenado (graceful shutdown).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aiokafka import AIOKafkaConsumer, ConsumerRecord
from aiokafka.errors import KafkaError
import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from backend.common.config import Settings, get_settings
from backend.consumer.spatial import SpatialMatcher

# Configuración de logging estructurado en español
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sismos.consumidor")


class EarthquakeConsumer:
    """
    Consumidor resiliente de eventos sísmicos que procesa mensajes de Kafka,
    valida su calidad, realiza geocodificación espacial y persiste en PostgreSQL.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        spatial_matcher: Optional[SpatialMatcher] = None,
    ) -> None:
        self.settings: Settings = settings or get_settings()
        self.spatial_matcher: SpatialMatcher = spatial_matcher or SpatialMatcher(
            self.settings.consumer.countries_geojson
        )
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._db_pool: Optional[AsyncConnectionPool] = None
        self._stop_event = asyncio.Event()

        # Métricas de operación
        self.stats: Dict[str, int] = {
            "total_recibidos": 0,
            "nuevos_insertados": 0,
            "revisiones_actualizadas": 0,
            "duplicados_ignorados": 0,
            "maritimos_sin_pais": 0,
            "con_pais_asignado": 0,
            "cuarentena": 0,
            "errores_bd": 0,
        }

    # -------------------------------------------------------------------------
    # CONEXIÓN Y RESILIENCIA CON POSTGRESQL Y KAFKA
    # -------------------------------------------------------------------------
    async def init_db_pool(self, max_retries: int = 15) -> None:
        """
        Inicializa el pool de conexiones asíncronas a PostgreSQL con reintentos.
        """
        dsn = self.settings.postgres.dsn
        logger.info(
            f"Conectando a PostgreSQL en {self.settings.postgres.host}:"
            f"{self.settings.postgres.port}/{self.settings.postgres.database}..."
        )

        self._db_pool = AsyncConnectionPool(
            conninfo=dsn,
            min_size=2,
            max_size=10,
            open=False,
            timeout=10.0,
        )

        for attempt in range(1, max_retries + 1):
            try:
                await self._db_pool.open()
                # Verificar conectividad real ejecutando una consulta trivial
                async with self._db_pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("SELECT 1;")
                logger.info("Pool de conexiones con PostgreSQL establecido exitosamente.")
                return
            except Exception as exc:
                if attempt == max_retries:
                    logger.critical(
                        f"Imposible conectar con PostgreSQL tras {max_retries} intentos: {exc}"
                    )
                    raise
                wait_sec = min(2 * attempt, 10)
                logger.warning(
                    f"PostgreSQL no disponible ({exc}). Reintento {attempt}/{max_retries} en {wait_sec}s..."
                )
                await asyncio.sleep(wait_sec)

    async def init_kafka_consumer(self, topics: Optional[List[str]] = None, max_retries: int = 15) -> None:
        """
        Inicializa y suscribe el consumidor de aiokafka con política de commit manual.
        """
        target_topics = topics or [
            self.settings.kafka.topic,
            self.settings.kafka.topic_replay,
        ]
        logger.info(
            f"Inicializando AIOKafkaConsumer. Servidores: '{self.settings.kafka.bootstrap_servers}', "
            f"Grupo: '{self.settings.kafka.consumer_group}', Topics: {target_topics}"
        )

        self._consumer = AIOKafkaConsumer(
            *target_topics,
            bootstrap_servers=self.settings.kafka.bootstrap_servers,
            group_id=self.settings.kafka.consumer_group,
            auto_offset_reset="earliest",
            enable_auto_commit=False,  # Garantía estricta at-least-once
            max_poll_records=self.settings.consumer.batch_size,
            client_id="sismos-consumer-service",
        )

        for attempt in range(1, max_retries + 1):
            try:
                await self._consumer.start()
                logger.info("Conexión con Apache Kafka establecida y suscripción activa.")
                return
            except Exception as exc:
                if attempt == max_retries:
                    logger.critical(
                        f"Imposible conectar con Apache Kafka tras {max_retries} intentos: {exc}"
                    )
                    raise
                wait_sec = min(2 * attempt, 10)
                logger.warning(
                    f"Broker Kafka no listo ({exc}). Reintento {attempt}/{max_retries} en {wait_sec}s..."
                )
                await asyncio.sleep(wait_sec)

    # -------------------------------------------------------------------------
    # VALIDACIÓN DE CALIDAD DE DATOS (6 DIMENSIONES)
    # -------------------------------------------------------------------------
    @staticmethod
    def parse_and_validate(raw_payload_str: str) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Evalúa la integridad del mensaje entrante según las directrices de calidad.

        Retorna:
            (es_valido, motivo_rechazo, datos_normalizados)
        """
        # Dimensión 1: Validez sintáctica del JSON
        try:
            payload = json.loads(raw_payload_str)
        except (json.JSONDecodeError, UnicodeDecodeError) as json_err:
            return False, f"JSON corrupto o truncado: {json_err}", None

        if not isinstance(payload, dict):
            return False, "La carga útil no es un objeto JSON válido", None

        # Soporte para formato envuelto (producido por USGSProducer) o directo GeoJSON Feature
        if "event" in payload and isinstance(payload["event"], dict):
            feature = payload["event"]
            source = str(payload.get("source", "usgs"))
            ingested_at_raw = payload.get("ingested_at")
            mode = str(payload.get("mode", "live"))
        else:
            feature = payload
            source = "direct_geojson"
            ingested_at_raw = None
            mode = "live"

        if mode not in ("live", "replay", "synthetic"):
            mode = "live"

        # Dimensión 2: Identificador del evento (Unicidad)
        event_id = feature.get("id")
        if not event_id or not isinstance(event_id, str) or not event_id.strip():
            return False, "Evento carece de identificador 'id' válido", None
        event_id = event_id.strip()

        # Dimensión 3: Tipo de entidad y evento
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            return False, f"Evento {event_id} carece de bloque 'properties'", None

        event_type = properties.get("type")
        if event_type != "earthquake":
            return (
                False,
                f"Tipo de evento no sismológico excluido: '{event_type}' (se requiere 'earthquake')",
                None,
            )

        # Dimensión 4: Validez espacial (Coordenadas en rango)
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            return False, f"Evento {event_id} carece de bloque 'geometry'", None

        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
            return False, f"Evento {event_id} tiene coordenadas incompletas: {coordinates}", None

        try:
            lon = float(coordinates[0])
            lat = float(coordinates[1])
        except (ValueError, TypeError):
            return False, f"Evento {event_id} tiene coordenadas no numéricas: {coordinates}", None

        if math.isnan(lon) or math.isnan(lat) or math.isinf(lon) or math.isinf(lat):
            return False, f"Evento {event_id} contiene coordenadas NaN o infinitas", None

        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            return (
                False,
                f"Coordenadas fuera de rango: longitud={lon} [-180, 180], latitud={lat} [-90, 90]",
                None,
            )

        # Profundidad (en km). Profundidad negativa es VÁLIDA (por encima del nivel del mar)
        depth: Optional[float] = None
        if len(coordinates) >= 3 and coordinates[2] is not None:
            try:
                depth_val = float(coordinates[2])
                if not (math.isnan(depth_val) or math.isinf(depth_val)):
                    depth = depth_val
            except (ValueError, TypeError):
                depth = None

        # Dimensión 5: Marcas temporales (Actualidad y consistencia)
        time_epoch_ms = properties.get("time")
        updated_epoch_ms = properties.get("updated")

        if time_epoch_ms is None or updated_epoch_ms is None:
            return False, f"Evento {event_id} carece de marca temporal 'time' o 'updated'", None

        try:
            time_epoch_int = int(time_epoch_ms)
            updated_epoch_int = int(updated_epoch_ms)
            time_dt = datetime.fromtimestamp(time_epoch_int / 1000.0, tz=timezone.utc)
            updated_dt = datetime.fromtimestamp(updated_epoch_int / 1000.0, tz=timezone.utc)
        except (ValueError, TypeError, OverflowError) as time_err:
            return False, f"Evento {event_id} contiene marcas temporales no parseables: {time_err}", None

        # Dimensión 6: Tratamiento explícito de completitud en magnitud
        # Magnitud nula o negativa es VÁLIDA según rúbrica (conservar tal cual)
        raw_mag = properties.get("mag")
        mag: Optional[float] = None
        if raw_mag is not None:
            try:
                mag_val = float(raw_mag)
                if not (math.isnan(mag_val) or math.isinf(mag_val)):
                    mag = mag_val
            except (ValueError, TypeError):
                mag = None

        # Metadatos descriptivos adicionales
        mag_type = properties.get("magType")
        place = properties.get("place")
        status = properties.get("status", "automatic")
        tsunami = 1 if properties.get("tsunami") in (1, "1", True) else 0

        raw_sig = properties.get("sig")
        sig: Optional[int] = None
        if raw_sig is not None:
            try:
                sig = int(raw_sig)
            except (ValueError, TypeError):
                sig = None

        # Fecha de ingesta local
        if ingested_at_raw:
            try:
                ingested_at_dt = datetime.fromisoformat(ingested_at_raw.replace("Z", "+00:00"))
            except Exception:
                ingested_at_dt = datetime.now(timezone.utc)
        else:
            ingested_at_dt = datetime.now(timezone.utc)

        normalized_data = {
            "id": event_id,
            "source": source,
            "ingested_at": ingested_at_dt,
            "mode": mode,
            "time": time_dt,
            "updated": updated_dt,
            "mag": mag,
            "mag_type": str(mag_type) if mag_type is not None else None,
            "place": str(place) if place is not None else None,
            "longitude": lon,
            "latitude": lat,
            "depth": depth,
            "status": str(status),
            "event_type": "earthquake",
            "tsunami": tsunami,
            "sig": sig,
            "feature": feature,
            "raw_payload": payload,
        }

        return True, None, normalized_data

    # -------------------------------------------------------------------------
    # AISLAMIENTO EN COLA DE CUARENTENA
    # -------------------------------------------------------------------------
    async def send_to_quarantine(
        self,
        event_id: Optional[str],
        reason: str,
        raw_payload: str,
    ) -> None:
        """
        Persiste un mensaje defectuoso o corrupto en la tabla de aislamiento
        'eventos_cuarentena' sin interrumpir el flujo del consumidor.
        """
        assert self._db_pool is not None, "Pool de base de datos no inicializado"
        self.stats["cuarentena"] += 1
        logger.warning(f"Desviando a cuarentena [ID={event_id or 'N/A'}]: {reason}")

        try:
            async with self._db_pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO eventos_cuarentena (event_id, reason, raw_payload, created_at)
                        VALUES (%s, %s, %s, NOW());
                        """,
                        (event_id, reason, raw_payload),
                    )
                await conn.commit()
        except Exception as exc:
            logger.error(f"Error al escribir en 'eventos_cuarentena': {exc}")

    # -------------------------------------------------------------------------
    # PERSISTENCIA TRANSACCIONAL E IDEMPOTENTE
    # -------------------------------------------------------------------------
    async def persist_event(self, data: Dict[str, Any]) -> str:
        """
        Ejecuta en una única transacción atómica de PostgreSQL:
        1. Inserción inmutable de auditoría en 'eventos_raw'.
        2. Ejecución de 'fn_ingestar_evento' que gestiona 'eventos' y 'eventos_versiones'.

        Retorna:
            Código de resultado: 'INSERTED_NEW', 'UPDATED_REVISION' o 'IGNORED_OUTDATED_OR_DUPLICATE'
        """
        assert self._db_pool is not None, "Pool de base de datos no inicializado"

        async with self._db_pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    # 1. Almacenamiento en eventos_raw (GeoJSON íntegro original)
                    await cur.execute(
                        """
                        INSERT INTO eventos_raw (id_evento, source, ingested_at, mode, raw_json)
                        VALUES (%s, %s, %s, %s, %s);
                        """,
                        (
                            data["id"],
                            data["source"],
                            data["ingested_at"],
                            data["mode"],
                            Jsonb(data["raw_payload"]),
                        ),
                    )

                    # 2. Inserción / Actualización versionada e idempotente
                    await cur.execute(
                        """
                        SELECT fn_ingestar_evento(
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        );
                        """,
                        (
                            data["id"],
                            data["time"],
                            data["updated"],
                            data["mag"],
                            data["mag_type"],
                            data["place"],
                            data["longitude"],
                            data["latitude"],
                            data["depth"],
                            data["country_code"],
                            data["status"],
                            data["event_type"],
                            data["tsunami"],
                            data["sig"],
                            data["mode"],
                            Jsonb(data["feature"]),
                        ),
                    )
                    row = await cur.fetchone()
                    resultado = row[0] if row else "UNKNOWN"

        return str(resultado)

    # -------------------------------------------------------------------------
    # PROCESAMIENTO DE UN MENSAJE INDIVIDUAL
    # -------------------------------------------------------------------------
    async def process_record(self, record: ConsumerRecord) -> str:
        """
        Procesa un ConsumerRecord de Kafka de principio a fin:
        - Decodificación y validación de calidad.
        - Enriquecimiento espacial.
        - Persistencia idempotente en BD.
        """
        self.stats["total_recibidos"] += 1

        try:
            raw_str = record.value.decode("utf-8")
        except UnicodeDecodeError as dec_err:
            await self.send_to_quarantine(
                event_id=None,
                reason=f"Error de decodificación UTF-8 en mensaje Kafka: {dec_err}",
                raw_payload=repr(record.value),
            )
            return "QUARANTINE_CODEC"

        is_valid, reject_reason, data = self.parse_and_validate(raw_str)

        if not is_valid:
            event_id = None
            try:
                temp_dict = json.loads(raw_str)
                event_id = temp_dict.get("id") or temp_dict.get("event", {}).get("id")
            except Exception:
                pass

            await self.send_to_quarantine(
                event_id=str(event_id) if event_id else None,
                reason=reject_reason or "Error de validación",
                raw_payload=raw_str,
            )
            return "QUARANTINE_VALIDATION"

        assert data is not None

        # Si el mensaje proviene del topic de replay, forzar modo 'replay'
        if record.topic == self.settings.kafka.topic_replay:
            data["mode"] = "replay"

        # Enriquecimiento espacial geométrico: Point-in-Polygon O(log N)
        lon = data["longitude"]
        lat = data["latitude"]
        match_country = self.spatial_matcher.match(lon, lat)

        if match_country:
            data["country_code"] = match_country["code"]
            self.stats["con_pais_asignado"] += 1
            country_label = f"{match_country['name_es']} [{match_country['code']}]"
        else:
            # Sismo en aguas abiertas / marítimo -> country_code = NULL
            data["country_code"] = None
            self.stats["maritimos_sin_pais"] += 1
            country_label = "Sin país asignado (Marítimo)"

        # Persistencia en PostgreSQL
        try:
            outcome = await self.persist_event(data)

            if outcome == "INSERTED_NEW":
                self.stats["nuevos_insertados"] += 1
            elif outcome == "UPDATED_REVISION":
                self.stats["revisiones_actualizadas"] += 1
            else:
                self.stats["duplicados_ignorados"] += 1

            mag_str = f"M {data['mag']}" if data["mag"] is not None else "M N/A"
            logger.info(
                f"[{record.topic}:{record.partition}@{record.offset}] | "
                f"ID: {data['id']:<12} | {outcome:<16} | {mag_str:<7} | {country_label}"
            )
            return outcome

        except Exception as db_err:
            self.stats["errores_bd"] += 1
            logger.exception(f"Error al persistir evento {data['id']} en PostgreSQL: {db_err}")
            raise

    # -------------------------------------------------------------------------
    # CICLO DE VIDA (START / RUN / STOP)
    # -------------------------------------------------------------------------
    async def start(self, topics: Optional[List[str]] = None) -> None:
        """
        Inicializa las conexiones a PostgreSQL y Apache Kafka.
        """
        await self.init_db_pool()
        await self.init_kafka_consumer(topics=topics)

    async def stop(self) -> None:
        """
        Detención ordenada (graceful shutdown) cerrando recursos de red.
        """
        logger.info("Iniciando detención limpia del Consumidor...")
        self._stop_event.set()

        if self._consumer:
            try:
                await self._consumer.stop()
                logger.info("AIOKafkaConsumer detenido de forma limpia.")
            except Exception as e:
                logger.error(f"Error al detener AIOKafkaConsumer: {e}")

        if self._db_pool:
            try:
                await self._db_pool.close()
                logger.info("Pool de PostgreSQL cerrado.")
            except Exception as e:
                logger.error(f"Error al cerrar pool de PostgreSQL: {e}")

        logger.info(
            f"Consumidor detenido completamente. Balance acumulado: "
            f"{self.stats['total_recibidos']} recibidos | "
            f"{self.stats['nuevos_insertados']} nuevos | "
            f"{self.stats['revisiones_actualizadas']} revisiones | "
            f"{self.stats['duplicados_ignorados']} ignorados | "
            f"{self.stats['cuarentena']} cuarentena | "
            f"{self.stats['maritimos_sin_pais']} marítimos"
        )

    async def run(
        self,
        once: bool = False,
        max_messages: Optional[int] = None,
        poll_timeout_ms: int = 1500,
    ) -> Dict[str, int]:
        """
        Bucle de consumo continuo con confirmación de offset tras persistencia.

        Args:
            once: Si es True, procesa los mensajes actualmente en cola hasta que
                  el topic quede vacío y sale (ideal para testing / batch).
            max_messages: Número máximo de mensajes a procesar antes de salir.
            poll_timeout_ms: Milisegundos de espera en poll() cuando no hay mensajes.
        """
        logger.info(
            f"Iniciando bucle de consumo de eventos. Modo 'once': {once}, "
            f"Máx mensajes: {max_messages or 'ilimitado'}."
        )

        try:
            assert self._consumer is not None, "El consumidor Kafka no ha sido iniciado"
            messages_processed = 0

            while not self._stop_event.is_set():
                # Extracción por lotes pequeños controlados
                msg_batch = await self._consumer.getmany(
                    timeout_ms=poll_timeout_ms,
                    max_records=self.settings.consumer.batch_size,
                )

                if not msg_batch:
                    if once:
                        logger.info("Modo '--once': No hay más mensajes en cola. Finalizando ejecución.")
                        break
                    await asyncio.sleep(0.1)
                    continue

                for tp, records in msg_batch.items():
                    for record in records:
                        if self._stop_event.is_set():
                            break

                        try:
                            # Procesar y persistir de forma transaccional en PostgreSQL
                            await self.process_record(record)
                            # Confirmar offset en Kafka SOLO tras éxito en BD (at-least-once)
                            await self._consumer.commit()
                            messages_processed += 1

                        except Exception as proc_err:
                            logger.error(
                                f"Fallo al procesar mensaje en {tp.topic}:{tp.partition}@{record.offset}: {proc_err}. "
                                f"NO se confirma offset en Kafka para permitir reprocesamiento seguro."
                            )
                            # Pequeña pausa para evitar saturar logs ante fallos persistentes de BD
                            await asyncio.sleep(2.0)

                        if max_messages and messages_processed >= max_messages:
                            logger.info(f"Límite alcanzado de {max_messages} mensajes procesados. Saliendo.")
                            return self.stats

                    if self._stop_event.is_set():
                        break

                if once and not msg_batch:
                    break

        except asyncio.CancelledError:
            logger.info("Tarea del consumidor cancelada.")
        finally:
            await self.stop()

        return self.stats


def handle_signals(consumer: EarthquakeConsumer, loop: asyncio.AbstractEventLoop) -> None:
    """
    Configura los manejadores de señales para captura limpia de SIGINT y SIGTERM
    en entornos Linux/Docker y Windows.
    """
    def _shutdown(sig_name: str) -> None:
        logger.warning(f"Señal {sig_name} recibida. Solicitando parada ordenada del consumidor...")
        consumer._stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _shutdown(s.name))
        except (NotImplementedError, AttributeError):
            signal.signal(sig, lambda s, f, s_name=sig.name: _shutdown(s_name))


def parse_arguments() -> argparse.Namespace:
    """
    Parsea los argumentos de línea de comandos para el Consumidor.
    """
    parser = argparse.ArgumentParser(
        description="Consumidor Kafka e Ingestor Sísmico con Enriquecimiento Espacial y Calidad"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Procesar los mensajes disponibles en la cola y salir (testing / batch)",
    )
    parser.add_argument(
        "--max-messages",
        type=int,
        default=None,
        help="Número máximo de mensajes a procesar antes de terminar",
    )
    parser.add_argument(
        "--topic",
        type=str,
        default=None,
        help="Topic específico al que suscribirse (por defecto los configurados en Settings)",
    )
    return parser.parse_args()


def main() -> None:
    """
    Punto de entrada para ejecutar el consumidor como proceso de servicio independiente.
    """
    args = parse_arguments()
    settings = get_settings()

    topics = [args.topic] if args.topic else None
    consumer = EarthquakeConsumer(settings=settings)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    handle_signals(consumer, loop)

    try:
        loop.run_until_complete(consumer.start(topics=topics))
        loop.run_until_complete(
            consumer.run(
                once=args.once,
                max_messages=args.max_messages,
            )
        )
    except KeyboardInterrupt:
        logger.info("Interrupción manual por teclado detectada.")
    except Exception as exc:
        logger.critical(f"Error fatal en el ciclo del consumidor: {exc}", exc_info=True)
        sys.exit(1)
    finally:
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        finally:
            loop.close()
            logger.info("Consumidor cerrado limpiamente.")


if __name__ == "__main__":
    main()
