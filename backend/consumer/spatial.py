"""
Módulo de enriquecimiento geográfico espacial (Point-in-Polygon).

Implementa la búsqueda espacial eficiente de países usando índices R-Tree
(Sort-Tile-Recursive Tree mediante Shapely STRtree) con complejidad asintótica
O(log N), superando la búsqueda secuencial exhaustiva O(N).

Reglas de negocio geoespaciales:
1. Prohibido extraer el país mediante análisis de texto (regex / split) sobre 'place'.
2. El cruce se realiza exclusivamente por evaluación geométrica exacta en WGS84 (EPSG:4326).
3. Sismos en aguas abiertas / marítimos devuelven None (sin país asignado).
4. Sismos en fronteras o polígonos solapados aplican un criterio determinista ordenando
   por código unívoco ADM0_A3.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from backend.common.config import get_settings

logger = logging.getLogger("sismos.consumidor.spatial")


class SpatialMatcher:
    """
    Motor de indexación y búsqueda espacial para asociar coordenadas sísmicas
    con entidades administrativas de países de Natural Earth.
    """

    def __init__(self, geojson_path: Optional[Path | str] = None) -> None:
        """
        Inicializa el índice espacial R-Tree cargando las geometrías de países.

        Args:
            geojson_path: Ruta al GeoJSON de países. Si no se proporciona,
                          se toma de la configuración centralizada del sistema.
        """
        resolved_path = self._resolve_path(geojson_path)
        logger.info(f"Cargando catálogo cartográfico de países desde '{resolved_path}'...")

        if not resolved_path.exists():
            raise FileNotFoundError(
                f"No se encontró el fichero de geometrías de países en '{resolved_path}'. "
                f"Verifique la configuración o la presencia de 'frontend/public/datos/paises.geojson'."
            )

        with open(resolved_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        features: List[Dict[str, Any]] = data.get("features", [])
        if not features:
            raise ValueError(f"El fichero GeoJSON '{resolved_path}' no contiene entidades ('features').")

        self.geometries: List[Any] = []
        self.country_metadata: List[Dict[str, Optional[str]]] = []

        for feature in features:
            geom_dict = feature.get("geometry")
            if not geom_dict:
                continue

            geom = shape(geom_dict)
            props = feature.get("properties", {})

            code = props.get("ADM0_A3")
            name_es = props.get("NAME_ES") or props.get("ADMIN")
            continent = props.get("CONTINENT")
            subregion = props.get("SUBREGION")

            self.geometries.append(geom)
            self.country_metadata.append({
                "code": code,
                "name_es": name_es,
                "continent": continent,
                "subregion": subregion,
            })

        # Construcción del índice espacial R-Tree balanceado (STRtree)
        # Complejidad temporal de construcción: O(N log N)
        # Complejidad temporal de consulta: O(log N)
        self.tree = STRtree(self.geometries)
        logger.info(
            f"Índice espacial STRtree inicializado con éxito. "
            f"{len(self.geometries)} entidades de países indexadas."
        )

    @staticmethod
    def _resolve_path(custom_path: Optional[Path | str]) -> Path:
        """
        Resuelve de forma robusta la ruta al archivo GeoJSON de países,
        evaluando configuración, rutas relativas y variables de entorno.
        """
        if custom_path:
            return Path(custom_path).resolve()

        settings = get_settings()
        default_path = settings.consumer.countries_geojson
        if default_path.exists():
            return default_path.resolve()

        # Fallbacks adicionales en caso de entornos de test o estructuras anidadas
        candidates = [
            settings.project_root / "frontend" / "public" / "datos" / "paises.geojson",
            Path("frontend/public/datos/paises.geojson"),
            Path("../frontend/public/datos/paises.geojson"),
            Path("/app/frontend/public/datos/paises.geojson"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()

        return default_path

    def match(self, lon: float, lat: float) -> Optional[Dict[str, Optional[str]]]:
        """
        Determina qué país contiene las coordenadas dadas (lon, lat).

        Args:
            lon: Longitud en grados decimales WGS84 [-180, 180].
            lat: Latitud en grados decimales WGS84 [-90, 90].

        Returns:
            Diccionario con {'code', 'name_es', 'continent', 'subregion'}
            o None si el punto cae en aguas abiertas / marítimo.
        """
        # Validación básica de coordenadas finitas
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            return None

        # GeoJSON y Shapely: X es longitud, Y es latitud
        point = Point(lon, lat)

        # Paso 1: Búsqueda logarítmica en el árbol espacial R-Tree: O(log N)
        # El predicado 'intersects' filtra directamente sobre el árbol y geometrías
        candidate_indices = self.tree.query(point, predicate="intersects")

        if len(candidate_indices) == 0:
            return None

        # Paso 2: Filtrado exacto de candidatos y desempate determinista
        matches: List[Dict[str, Optional[str]]] = []
        for idx in candidate_indices:
            int_idx = int(idx)
            geom = self.geometries[int_idx]
            if geom.intersects(point):
                matches.append(self.country_metadata[int_idx])

        if not matches:
            return None

        if len(matches) == 1:
            return matches[0]

        # Desempate determinista ante fronteras compartidas o solapes:
        # Ordenar alfabéticamente por código unívoco ADM0_A3
        matches.sort(key=lambda item: item["code"] or "")
        return matches[0]
