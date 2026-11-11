"""
Script de Descarga y Carga del Histórico 2025
================================================
Descarga el catálogo completo del año 2025 de USGS con:
- minmagnitude=4
- eventtype=earthquake
- Ámbito: mundial (WGS84)

Estrategia:
- Particiona el año mes a mes para mantenerse muy por debajo del límite de 20.000 eventos de USGS.
- Deduplica los eventos compartidos en los límites de cada ventana temporal.
- Almacena una instantánea persistente en data/historico_2025.geojson para reutilización offline.
- Realiza la asignación espacial de país mediante Shapely (STRtree) e inserta en la tabla historico_2025.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
import httpx
import psycopg
from psycopg.rows import dict_row

from backend.common.config import settings
from backend.consumer.spatial import SpatialMatcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [historico] %(message)s")
logger = logging.getLogger("historico")

OUTPUT_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "historico_2025.geojson")

MONTHS_2025 = [
    ("2025-01-01T00:00:00Z", "2025-02-01T00:00:00Z"),
    ("2025-02-01T00:00:00Z", "2025-03-01T00:00:00Z"),
    ("2025-03-01T00:00:00Z", "2025-04-01T00:00:00Z"),
    ("2025-04-01T00:00:00Z", "2025-05-01T00:00:00Z"),
    ("2025-05-01T00:00:00Z", "2025-06-01T00:00:00Z"),
    ("2025-06-01T00:00:00Z", "2025-07-01T00:00:00Z"),
    ("2025-07-01T00:00:00Z", "2025-08-01T00:00:00Z"),
    ("2025-08-01T00:00:00Z", "2025-09-01T00:00:00Z"),
    ("2025-09-01T00:00:00Z", "2025-10-01T00:00:00Z"),
    ("2025-10-01T00:00:00Z", "2025-11-01T00:00:00Z"),
    ("2025-11-01T00:00:00Z", "2025-12-01T00:00:00Z"),
    ("2025-12-01T00:00:00Z", "2026-01-01T00:00:00Z")
]

async def download_month(client: httpx.AsyncClient, start: str, end: str) -> list[dict]:
    url = "https://earthquake.usgs.gov/fdsnws/event/1/query"
    params = {
        "format": "geojson",
        "starttime": start,
        "endtime": end,
        "minmagnitude": "4",
        "eventtype": "earthquake",
        "orderby": "time-asc"
    }
    logger.info(f"Descargando rango: {start} -> {end}...")
    for attempt in range(1, 4):
        try:
            resp = await client.get(url, params=params, timeout=30.0)
            if resp.status_code == 200:
                data = resp.json()
                features = data.get("features", [])
                logger.info(f"Rango {start[:10]}: {len(features)} eventos obtenidos.")
                if len(features) >= 20000:
                    logger.warning(f"¡Atención! {len(features)} eventos alcanzaron el límite de 20.000 de USGS.")
                return features
            elif resp.status_code == 429:
                logger.warning(f"HTTP 429 Too Many Requests. Esperando 5s...")
                await asyncio.sleep(5)
            else:
                logger.error(f"HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"Error en intento {attempt}: {e}")
            await asyncio.sleep(2)
    return []

async def fetch_full_year_2025() -> list[dict]:
    # Si ya existe el archivo en disco, reutilizarlo
    if os.path.exists(OUTPUT_FILE) and os.path.getsize(OUTPUT_FILE) > 1000:
        logger.info(f"Reutilizando archivo local existente: {OUTPUT_FILE}")
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("features", [])

    all_features = []
    seen_ids = set()

    async with httpx.AsyncClient() as client:
        for start, end in MONTHS_2025:
            month_feats = await download_month(client, start, end)
            for feat in month_feats:
                fid = feat.get("id")
                if fid and fid not in seen_ids:
                    seen_ids.add(fid)
                    all_features.append(feat)
            # Pequeña pausa de cortesía para no saturar la API oficial de USGS
            await asyncio.sleep(0.5)

    logger.info(f"Descarga finalizada: {len(all_features)} eventos únicos del año 2025 (mag >= 4).")
    
    # Guardar en disco para reproducibilidad offline
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "type": "FeatureCollection",
            "metadata": {
                "generated": int(datetime.now(timezone.utc).timestamp() * 1000),
                "source": "USGS FDSNWS Event Catalog 2025",
                "count": len(all_features),
                "filters": "minmagnitude=4, eventtype=earthquake"
            },
            "features": all_features
        }, f)
    logger.info(f"Histórico guardado en caché local: {OUTPUT_FILE}")
    return all_features

async def load_into_postgres(features: list[dict]):
    logger.info(f"Iniciando carga de {len(features)} eventos en la tabla 'historico_2025'...")
    spatial = SpatialMatcher(settings.country_geojson_path)

    try:
        async with await psycopg.AsyncConnection.connect(settings.postgres_dsn, autocommit=False) as conn:
            async with conn.cursor() as cur:
                inserted = 0
                for feat in features:
                    fid = feat.get("id")
                    props = feat.get("properties") or {}
                    geom = feat.get("geometry") or {}
                    coords = geom.get("coordinates") or []
                    if len(coords) < 3 or not fid:
                        continue

                    lon, lat, depth = float(coords[0]), float(coords[1]), float(coords[2])
                    mag = float(props["mag"]) if props.get("mag") is not None else None
                    if mag is None:
                        continue  # Requisito histórico: mag >= 4

                    mag_type = props.get("magType")
                    place = props.get("place")
                    time_ms = props.get("time")
                    event_time = datetime.fromtimestamp(time_ms / 1000.0, tz=timezone.utc)

                    # Integración espacial punto en polígono
                    cm = spatial.match(lon, lat)

                    await cur.execute(
                        """
                        INSERT INTO historico_2025 (
                            event_id, mag, mag_type, place, event_time,
                            country_id, country_name, lon, lat, depth_km
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (event_id) DO NOTHING
                        """,
                        (fid, mag, mag_type, place, event_time, cm.country_id, cm.country_name, lon, lat, depth)
                    )
                    inserted += 1

                await conn.commit()
                logger.info(f"Carga histórica completada con éxito: {inserted} eventos insertados en PostgreSQL.")
    except Exception as e:
        logger.error(f"Error cargando histórico en PostgreSQL: {e}")

async def main():
    features = await fetch_full_year_2025()
    await load_into_postgres(features)

if __name__ == "__main__":
    asyncio.run(main())

