"""
Módulo Productor de eventos sísmicos en tiempo real (USGS -> Kafka).

Responsabilidades:
1. Sondeo periódico (polling) del feed GeoJSON de USGS (all_day.geojson).
2. Resiliencia HTTP con reintentos y retroceso exponencial (backoff) ante fallos
   de red, errores 429 (rate-limit) y 5xx (servidor).
3. Persistencia de estado local (id, updated) en memoria y disco (JSON atómico)
   para evitar la duplicación de eventos tras reinicios del servicio.
4. Filtrado estricto de eventos no sismológicos (properties.type != 'earthquake')
   con registro estructurado del motivo de exclusión.
5. Detección precisa de sismos NUEVOS y REVISIONES de sismos existentes.
6. Publicación a Kafka usando aiokafka:
   - Clave particionada por event['id'] (UTF-8).
   - Payload enriquecido con metadatos: source, ingested_at, mode, event.
   - Confirmación estricta de entrega (ACK) antes de actualizar el estado local.
7. Cierre limpio (graceful shutdown) gestionando señales SIGINT y SIGTERM.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

from backend.common.config import Settings, get_settings

# Configuración de logging estructurado en español
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sismos.productor")


class USGSProducer:
    """
    Productor asíncrono que extrae novedades del feed sísmico de USGS
    y las publica en Apache Kafka garantizando ordenación y deduplicación.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings: Settings = settings or get_settings()
        self.state_file: Path = self.settings.producer.state_file
        # Estado en memoria: {event_id: updated_timestamp_ms}
        self.state: Dict[str, int] = {}
        self._producer: Optional[AIOKafkaProducer] = None
        self._http_client: Optional[httpx.AsyncClient] = None
        self._stop_event = asyncio.Event()

        # Cargar estado previo desde disco si existe
        self.load_state()

    # -------------------------------------------------------------------------
    # GESTIÓN DEL ESTADO PERSISTENTE (DEDUPLICACIÓN Y VERSIONADO)
    # -------------------------------------------------------------------------
    def load_state(self) -> None:
        """
        Carga el mapa de pares (id, updated) desde el archivo de estado en disco.
        Si el archivo no existe o está corrupto, inicia con un estado limpio.
        """
        if not self.state_file.exists():
            logger.info(
                f"No se encontró archivo de estado previo en '{self.state_file}'. "
                f"Iniciando con estado en memoria vacío."
            )
            self.state = {}
            return

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict):
                # Asegurar que las marcas temporales sean enteros
                self.state = {str(k): int(v) for k, v in data.items() if isinstance(v, (int, float))}
                logger.info(
                    f"Estado cargado correctamente desde '{self.state_file}': "
                    f"{len(self.state)} eventos registrados históricamente."
                )
            else:
                logger.warning(
                    f"Formato no válido en '{self.state_file}'. Se reiniciará el estado."
                )
                self.state = {}
        except Exception as exc:
            logger.error(
                f"Error al leer el archivo de estado '{self.state_file}': {exc}. "
                f"Se mantendrá el estado en memoria para no interrumpir el flujo."
            )
            self.state = {}

    def save_state(self) -> None:
        """
        Guarda el estado en memoria en disco de forma atómica (archivo temporal + reemplazo)
        para garantizar consistencia ante cortes abruptos o caídas de contenedor.
        """
        try:
            # Asegurar que el directorio contenedor exista
            self.state_file.parent.mkdir(parents=True, exist_ok=True)

            # Poda suave si se sobrepasa el límite configurado de entradas
            if len(self.state) > self.settings.producer.max_state_entries:
                logger.info(
                    f"Podando estado: {len(self.state)} eventos superan el límite de "
                    f"{self.settings.producer.max_state_entries}. Manteniendo los más recientes."
                )
                # Ordenar por updated descendente y conservar los N más recientes
                sorted_items = sorted(self.state.items(), key=lambda item: item[1], reverse=True)
                self.state = dict(sorted_items[: self.settings.producer.max_state_entries])

            tmp_path = self.state_file.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)

            # Reemplazo atómico en el sistema de archivos
            os.replace(tmp_path, self.state_file)
            logger.debug(f"Estado persistido con éxito ({len(self.state)} eventos en disco).")
        except Exception as exc:
            logger.error(f"Error crítico al guardar el estado en disco '{self.state_file}': {exc}")

    # -------------------------------------------------------------------------
    # CLIENTE HTTP RESILIENTE CON RETROCESO EXPONENCIAL
    # -------------------------------------------------------------------------
    async def fetch_feed_with_retry(self) -> Optional[Dict[str, Any]]:
        """
        Realiza una petición HTTP GET a la URL del feed USGS.
        Implementa reintentos con backoff exponencial y jitter aleatorio ante:
        - Errores de conexión / red
        - Timeouts
        - Respuestas HTTP 429 (Rate Limit)
        - Respuestas HTTP 5xx (Errores del servidor)
        """
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.usgs.timeout_seconds),
                headers={"User-Agent": "ObservatorioSismico/1.0 (Python/httpx)"},
            )

        url = self.settings.usgs.feed_url
        max_retries = self.settings.usgs.max_retries

        for attempt in range(1, max_retries + 1):
            try:
                logger.debug(f"Consultando feed USGS: {url} (intento {attempt}/{max_retries})")
                response = await self._http_client.get(url)

                if response.status_code == 200:
                    try:
                        return response.json()
                    except json.JSONDecodeError as err:
                        logger.error(
                            f"Respuesta de USGS no es un JSON válido: {err}. "
                            f"Se descarta este ciclo sin alterar el estado."
                        )
                        return None

                elif response.status_code == 204:
                    logger.info("USGS respondió HTTP 204 (Sin contenido). Reintentando en el próximo intervalo.")
                    return None

                elif response.status_code == 429 or response.status_code >= 500:
                    # Error transitorio o saturación: aplicar retroceso
                    wait_time = (self.settings.usgs.backoff_factor ** (attempt - 1)) + random.uniform(0.5, 1.5)
                    logger.warning(
                        f"USGS respondió HTTP {response.status_code}. Intento {attempt}/{max_retries}. "
                        f"Pausando {wait_time:.2f}s antes de reintentar..."
                    )
                    if attempt < max_retries:
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"Agotados los reintentos tras HTTP {response.status_code} de USGS.")
                        return None

                else:
                    # Errores 4xx irrecuperables (404, 403, etc.)
                    logger.error(f"Error HTTP no recuperable de USGS: {response.status_code} - {response.text[:200]}")
                    return None

            except (httpx.TimeoutException, httpx.NetworkError) as net_err:
                wait_time = (self.settings.usgs.backoff_factor ** (attempt - 1)) + random.uniform(0.5, 1.5)
                logger.warning(
                    f"Fallo de conexión con USGS ({type(net_err).__name__}: {net_err}). "
                    f"Intento {attempt}/{max_retries}. Reintentando en {wait_time:.2f}s..."
                )
                if attempt < max_retries:
                    await asyncio.sleep(wait_time)
                else:
                    logger.error("Límite de reintentos alcanzado por errores de red continuados con USGS.")
                    return None
            except Exception as unk_err:
                logger.exception(f"Excepción inesperada al consultar USGS: {unk_err}")
                return None

        return None

    # -------------------------------------------------------------------------
    # VALIDACIÓN, FILTRADO Y DETECCIÓN DE NOVEDADES
    # -------------------------------------------------------------------------
    @staticmethod
    def is_valid_earthquake(feature: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Valida que la entidad GeoJSON cumpla con las especificaciones del proyecto
        y corresponda a un sismo real ('earthquake').

        Retorna:
            (es_valido, motivo_exclusion)
        """
        if not isinstance(feature, dict):
            return False, "La entidad no es un diccionario GeoJSON válido"

        event_id = feature.get("id")
        if not event_id:
            return False, "Entidad GeoJSON carece de identificador ('id')"

        properties = feature.get("properties")
        if not isinstance(properties, dict):
            return False, f"Evento {event_id} carece de bloque 'properties'"

        event_type = properties.get("type")
        if event_type != "earthquake":
            return False, f"properties.type='{event_type}' (solo se procesan terremotos 'earthquake')"

        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            return False, f"Evento {event_id} carece de bloque 'geometry'"

        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            return False, f"Evento {event_id} tiene coordenadas inválidas o incompletas: {coordinates}"

        updated = properties.get("updated")
        if updated is None:
            return False, f"Evento {event_id} carece de marca temporal 'properties.updated'"

        return True, None

    # -------------------------------------------------------------------------
    # CICLO DE SONDEO Y PUBLICACIÓN EN KAFKA
    # -------------------------------------------------------------------------
    async def poll_and_publish(self) -> Dict[str, int]:
        """
        Ejecuta un ciclo completo de:
        1. Descarga del feed.
        2. Clasificación de eventos (Nuevo, Revisión, Sin cambios, Excluido).
        3. Publicación en Kafka esperando confirmación (ACK).
        4. Actualización del estado persistente.

        Retorna métricas del ciclo ejecutado.
        """
        stats = {
            "total_recibidos": 0,
            "nuevos": 0,
            "revisiones": 0,
            "sin_cambios": 0,
            "excluidos": 0,
            "errores_publicacion": 0,
        }

        feed_data = await self.fetch_feed_with_retry()
        if not feed_data or "features" not in feed_data:
            logger.info("Ciclo de sondeo finalizado sin datos que procesar.")
            return stats

        features: List[Dict[str, Any]] = feed_data.get("features", [])
        stats["total_recibidos"] = len(features)

        # Procesar los eventos en orden cronológico (los más antiguos primero en este feed)
        # o preservando el orden provisto por USGS
        for feature in features:
            if self._stop_event.is_set():
                logger.info("Interrupción solicitada durante el procesamiento del lote.")
                break

            event_id = feature.get("id", "desconocido")
            is_valid, exclusion_reason = self.is_valid_earthquake(feature)

            if not is_valid:
                stats["excluidos"] += 1
                logger.info(f"Evento excluido [{event_id}]: {exclusion_reason}")
                continue

            properties = feature["properties"]
            updated: int = int(properties["updated"])
            mag = properties.get("mag")
            place = properties.get("place", "Ubicación no especificada")

            # Clasificación contra el estado local
            prev_updated = self.state.get(event_id)
            is_new = prev_updated is None
            is_revision = not is_new and updated > prev_updated

            if not is_new and not is_revision:
                # Evento ya procesado con updated igual o menor
                stats["sin_cambios"] += 1
                continue

            tipo_cambio = "NUEVO" if is_new else f"REVISIÓN (prev={prev_updated} -> nuevo={updated})"

            # Construcción del payload formal para Kafka
            now_iso = datetime.now(timezone.utc).isoformat()
            message_payload = {
                "source": "usgs_feed",
                "ingested_at": now_iso,
                "mode": "live",
                "event": feature,
            }

            key_bytes = str(event_id).encode("utf-8")
            value_bytes = json.dumps(message_payload, ensure_ascii=False).encode("utf-8")

            # Publicación a Kafka con espera obligatoria de confirmación (ACK)
            try:
                assert self._producer is not None, "El productor Kafka no está iniciado"
                record_meta = await self._producer.send_and_wait(
                    topic=self.settings.kafka.topic,
                    key=key_bytes,
                    value=value_bytes,
                )

                # ÉXITO: Actualizar el estado en memoria únicamente tras el ACK confirmado
                self.state[event_id] = updated

                if is_new:
                    stats["nuevos"] += 1
                else:
                    stats["revisiones"] += 1

                logger.info(
                    f"Publicado en Kafka [{self.settings.kafka.topic}:{record_meta.partition}@"
                    f"{record_meta.offset}] | ID: {event_id:<12} | {tipo_cambio} | "
                    f"M {mag if mag is not None else 'N/A'} | {place}"
                )

            except KafkaError as k_err:
                stats["errores_publicacion"] += 1
                logger.error(
                    f"Fallo al publicar evento {event_id} en Kafka: {k_err}. "
                    f"NO se actualizará el estado para reintentarlo en el siguiente ciclo."
                )
            except Exception as pub_err:
                stats["errores_publicacion"] += 1
                logger.exception(f"Error inesperado al publicar evento {event_id}: {pub_err}")

        # Guardar en disco el estado actualizado tras procesar el lote completo
        self.save_state()

        logger.info(
            f"Resumen del ciclo: {stats['total_recibidos']} examinados | "
            f"{stats['nuevos']} nuevos publicados | {stats['revisiones']} revisiones | "
            f"{stats['sin_cambios']} sin cambios | {stats['excluidos']} excluidos | "
            f"{stats['errores_publicacion']} errores | Total en estado: {len(self.state)}"
        )

        return stats

    # -------------------------------------------------------------------------
    # CICLO DE VIDA (START / RUN / STOP)
    # -------------------------------------------------------------------------
    async def start(self) -> None:
        """
        Inicializa las conexiones de Kafka y del cliente HTTP.
        """
        logger.info("Inicializando productor Kafka...")
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.settings.kafka.bootstrap_servers,
            acks="all",
            enable_idempotence=True,
            client_id="sismos-producer-service",
            max_request_size=2097152,  # 2MB para admitir GeoJSONs complejos
        )

        # Reintentar conexión inicial a Kafka si el broker está arrancando
        max_init_retries = 15
        for i in range(1, max_init_retries + 1):
            try:
                logger.info(
                    f"Conectando a broker Kafka en '{self.settings.kafka.bootstrap_servers}' "
                    f"(intento {i}/{max_init_retries})..."
                )
                await self._producer.start()
                logger.info("Conexión con Apache Kafka establecida exitosamente.")
                break
            except Exception as conn_err:
                if i == max_init_retries:
                    logger.critical(f"No fue posible conectar con Kafka tras {max_init_retries} intentos: {conn_err}")
                    raise
                wait_s = min(2 * i, 10)
                logger.warning(f"Kafka no listo ({conn_err}). Esperando {wait_s}s...")
                await asyncio.sleep(wait_s)

        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.usgs.timeout_seconds),
            headers={"User-Agent": "ObservatorioSismico/1.0 (Python/httpx)"},
        )

    async def stop(self) -> None:
        """
        Cierre graceful del productor, asegurando que todos los mensajes pendientes
        reciban ACK y el estado en disco quede salvado.
        """
        logger.info("Iniciando detención limpia del Productor USGS...")
        self._stop_event.set()

        if self._producer:
            try:
                await self._producer.stop()
                logger.info("AIOKafkaProducer detenido de forma limpia.")
            except Exception as e:
                logger.error(f"Error al detener AIOKafkaProducer: {e}")

        if self._http_client and not self._http_client.is_closed:
            try:
                await self._http_client.aclose()
                logger.info("Cliente HTTP cerrado.")
            except Exception as e:
                logger.error(f"Error al cerrar cliente HTTP: {e}")

        # Guardado final de estado
        self.save_state()
        logger.info("Productor detenido completamente.")

    async def run(self, once: bool = False, poll_interval: Optional[int] = None) -> None:
        """
        Bucle principal de ejecución periódica del productor.

        Args:
            once: Si es True, ejecuta únicamente un ciclo y finaliza (ideal para testing o batch).
            poll_interval: Intervalo en segundos entre consultas (por defecto desde configuración).
        """
        interval = poll_interval or self.settings.usgs.poll_interval_seconds
        logger.info(
            f"Iniciando bucle de extracción USGS. Intervalo configurado: {interval} segundos. "
            f"Topic destino: '{self.settings.kafka.topic}'. Modo una sola pasada: {once}."
        )

        try:
            await self.start()

            while not self._stop_event.is_set():
                start_time = asyncio.get_event_loop().time()
                try:
                    await self.poll_and_publish()
                except Exception as cycle_err:
                    logger.exception(f"Error durante la ejecución del ciclo de sondeo: {cycle_err}")

                if once:
                    logger.info("Ejecución en modo '--once' finalizada.")
                    break

                # Esperar el intervalo ajustado considerando el tiempo consumido en el ciclo
                elapsed = asyncio.get_event_loop().time() - start_time
                sleep_time = max(0.0, float(interval) - elapsed)
                logger.debug(f"Pausa de {sleep_time:.2f}s hasta el próximo sondeo...")

                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=sleep_time)
                except asyncio.TimeoutError:
                    # Se agotó el tiempo de espera normal del intervalo: proceder al siguiente sondeo
                    pass

        except asyncio.CancelledError:
            logger.info("Tarea del productor cancelada.")
        finally:
            await self.stop()


def handle_signals(producer: USGSProducer, loop: asyncio.AbstractEventLoop) -> None:
    """
    Configura los manejadores de señales para captura de SIGINT y SIGTERM,
    compatible tanto con sistemas Unix como con Windows.
    """
    def _shutdown_handler(sig_name: str) -> None:
        logger.warning(f"Señal {sig_name} recibida. Solicitando detención segura...")
        producer._stop_event.set()

    # Manejo estándar de señales
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            # Unix / POSIX
            loop.add_signal_handler(sig, lambda s=sig: _shutdown_handler(s.name))
        except (NotImplementedError, AttributeError):
            # Windows (ProactorEventLoop no soporta add_signal_handler)
            signal.signal(sig, lambda s, f, s_name=sig.name: _shutdown_handler(s_name))


def parse_arguments() -> argparse.Namespace:
    """
    Parsea los argumentos de línea de comandos.
    """
    parser = argparse.ArgumentParser(
        description="Extractor y Productor de Terremotos USGS hacia Apache Kafka"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Intervalo de sondeo en segundos (sobrescribe USGS_POLL_INTERVAL_SECONDS)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Ejecutar una sola iteración de extracción y salir (útil para auditoría y testing)",
    )
    parser.add_argument(
        "--state-file",
        type=str,
        default=None,
        help="Ruta personalizada para el archivo de estado de deduplicación",
    )
    return parser.parse_args()


def main() -> None:
    """
    Punto de entrada principal para ejecutar el productor como proceso independiente.
    """
    args = parse_arguments()
    settings = get_settings()

    if args.state_file:
        settings.producer.state_file = Path(args.state_file)

    producer = USGSProducer(settings=settings)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    handle_signals(producer, loop)

    try:
        loop.run_until_complete(producer.run(once=args.once, poll_interval=args.interval))
    except KeyboardInterrupt:
        logger.info("Interrupción por teclado detectada.")
    finally:
        try:
            # Procesar tareas pendientes
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        finally:
            loop.close()
            logger.info("Bucle de eventos cerrado. Fin del programa.")


if __name__ == "__main__":
    main()
