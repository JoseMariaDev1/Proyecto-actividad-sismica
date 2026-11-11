"""
Script de Reproducción Histórica Acelerada
============================================
Permite realizar una demostración completa y en directo del pipeline
sin depender de que ocurran nuevos terremotos en USGS durante la defensa.

Flujo de la reproducción:
1. Lee una muestra representativa de eventos históricos reales ordenados cronológicamente.
2. Inyecta casos de prueba controlados:
   - Duplicado idéntico (comprobar idempotencia)
   - Revisión posterior con cambio de magnitud (comprobar actualización de estado actual)
   - Revisión antigua recibida tarde (comprobar que no sobrescribe la más reciente)
   - Magnitud ausente/nula (comprobar tratamiento ND)
   - Coordenadas inválidas (comprobar cuarentena)
   - Evento marítimo (comprobar 'Sin país asignado')
3. Emite los mensajes en Kafka con mode="replay" a velocidad configurable.
4. El consumidor procesa los mensajes aislando los datos en mode='replay'.
5. El panel Angular muestra la etiqueta y banner de 'REPRODUCCIÓN HISTÓRICA'.
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Asegurar que la raíz del proyecto está en sys.path para importar backend
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from aiokafka import AIOKafkaProducer
from backend.common.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [replay] %(message)s")
logger = logging.getLogger("replay")

HISTORICAL_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "historico_2025.geojson")
HISTORICAL_SAMPLE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "historico_2025_sample.geojson")

def build_demo_suite() -> list[dict]:
    """Genera una secuencia controlada de eventos para verificar las reglas de aceptación."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    
    events = [
        # 1. Terremoto estándar en España (Granada)
        {
            "id": "replay-esp-1",
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-3.6, 37.18, 10.0]},
            "properties": {
                "type": "earthquake",
                "mag": 4.5,
                "magType": "mb",
                "place": "12 km SW de Granada, España",
                "time": now_ms - 3600000,
                "updated": now_ms - 3500000
            }
        },
        # 2. Duplicado idéntico del evento anterior (debe ignorarse sin duplicar filas)
        {
            "id": "replay-esp-1",
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-3.6, 37.18, 10.0]},
            "properties": {
                "type": "earthquake",
                "mag": 4.5,
                "magType": "mb",
                "place": "12 km SW de Granada, España",
                "time": now_ms - 3600000,
                "updated": now_ms - 3500000
            }
        },
        # 3. Revisión posterior del mismo terremoto (magnitud recalculada a 4.8)
        {
            "id": "replay-esp-1",
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-3.6, 37.18, 12.0]},
            "properties": {
                "type": "earthquake",
                "mag": 4.8,
                "magType": "mw",
                "place": "10 km SW de Granada, España (revisado)",
                "time": now_ms - 3600000,
                "updated": now_ms - 3000000
            }
        },
        # 4. Versión antigua que llega con retraso (debe ir al historial sin pisar la 4.8)
        {
            "id": "replay-esp-1",
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-3.6, 37.18, 10.0]},
            "properties": {
                "type": "earthquake",
                "mag": 4.2,
                "magType": "ml",
                "place": "Granada (versión preliminar tardía)",
                "time": now_ms - 3600000,
                "updated": now_ms - 3800000  # Anterior a la versión vigente
            }
        },
        # 5. Terremoto con Magnitud Nula (debe conservarse y mostrarse como ND)
        {
            "id": "replay-null-mag",
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [139.75, 35.68, 55.0]},
            "properties": {
                "type": "earthquake",
                "mag": None,
                "magType": None,
                "place": "Near Tokyo, Japan (Magnitud no consolidada)",
                "time": now_ms - 7200000,
                "updated": now_ms - 7000000
            }
        },
        # 6. Terremoto con Coordenadas Inválidas (debe enviarse a cuarentena)
        {
            "id": "replay-corrupto-coords",
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [999.0, 145.0, -10.0]},
            "properties": {
                "type": "earthquake",
                "mag": 5.1,
                "magType": "mb",
                "place": "Punto astronómico imposible",
                "time": now_ms - 5000000,
                "updated": now_ms - 4900000
            }
        },
        # 7. Terremoto Marítimo en Dorsal Atlántica (debe asignarse como 'Sin país asignado')
        {
            "id": "replay-maritimo-1",
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-35.5, 12.4, 10.0]},
            "properties": {
                "type": "earthquake",
                "mag": 5.9,
                "magType": "mww",
                "place": "Central Mid-Atlantic Ridge",
                "time": now_ms - 10000000,
                "updated": now_ms - 9500000
            }
        },
        # 8. Terremoto profundo en Fosa de Kermadec (Nueva Zelanda)
        {
            "id": "replay-nz-profundo",
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-178.5, -31.2, 385.0]},
            "properties": {
                "type": "earthquake",
                "mag": 6.3,
                "magType": "mwb",
                "place": "Kermadec Islands Region",
                "time": now_ms - 12000000,
                "updated": now_ms - 11000000
            }
        }
    ]
    return events

async def run_replay(speed_delay_seconds: float = 0.5):
    logger.info("Iniciando productor de reproducción histórica...")
    # Si se ejecuta desde el host (fuera de Docker), Kafka escucha en localhost:9092
    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    # Si viene con nombre del contenedor 'kafka:9092' y estamos fuera de docker, usar localhost:9092
    if bootstrap_servers == "kafka:9092":
        bootstrap_servers = "localhost:9092"

    topic = os.getenv("KAFKA_TOPIC_REPLAY", getattr(settings.kafka, "topic_replay", "terremotos-replay"))

    producer = AIOKafkaProducer(
        bootstrap_servers=bootstrap_servers,
        acks="all"
    )
    await producer.start()
    logger.info(f"Conectado a Kafka en {bootstrap_servers}.")

    events = build_demo_suite()

    # Si hay eventos históricos descargados, agregar una muestra cronológica
    target_file = HISTORICAL_FILE if os.path.exists(HISTORICAL_FILE) else (HISTORICAL_SAMPLE if os.path.exists(HISTORICAL_SAMPLE) else None)
    if target_file:
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                hist_data = json.load(f)
                hist_features = hist_data.get("features", [])
                logger.info(f"Cargando muestra de 15 eventos de {target_file}...")
                events.extend(hist_features[:15])
        except Exception as e:
            logger.warning(f"No se pudo cargar muestra de archivo histórico: {e}")

    logger.info(f"Total de eventos a reproducir: {len(events)}. Intervalo entre eventos: {speed_delay_seconds}s.")

    try:
        for idx, feat in enumerate(events, 1):
            fid = feat.get("id", f"replay-{idx}")
            payload = {
                "source": "historical_replay_producer",
                "ingested_at": datetime.now(timezone.utc).isoformat(),
                "mode": "replay",
                "event": feat
            }

            key_bytes = fid.encode("utf-8")
            val_bytes = json.dumps(payload).encode("utf-8")

            # Se envía al topic de replay configurado
            await producer.send_and_wait(topic=topic, key=key_bytes, value=val_bytes)
            logger.info(f"[{idx}/{len(events)}] Publicado evento de reproducción: '{fid}' en topic '{topic}'.")
            await asyncio.sleep(speed_delay_seconds)

        logger.info("¡Reproducción completada con éxito! Todos los eventos de prueba han sido emitidos.")
    finally:
        await producer.stop()
        logger.info("Productor de reproducción detenido.")

if __name__ == "__main__":
    delay = float(sys.argv[1]) if len(sys.argv) > 1 else 0.5
    asyncio.run(run_replay(delay))
