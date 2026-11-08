"""
Batería de pruebas automatizadas para el API REST del Observatorio de Actividad Sísmica.

Compatible tanto con el runner estándar 'unittest' de Python 3.12 como con 'pytest':
1. Endpoint /api/salud (estado OK y manejo de errores de base de datos).
2. Endpoint /api/eventos:
   - Formato GeoJSON RFC 7946 (FeatureCollection).
   - Metadatos requeridos por CONTRATO-API.md.
   - Filtros por país, magnitud, fecha, modo y paginación.
   - Manejo de valores nulos (magnitud, profundidad, país marítimo).
3. Endpoint /api/estadisticas:
   - Cálculos analíticos, distribuciones, ventanas horarias UTC y top países.
4. Endpoint /api/paises:
   - Retorno del catálogo geográfico.
5. Cabeceras CORS y soporte para ngrok (ngrok-skip-browser-warning).
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from httpx import ASGITransport, AsyncClient

# Asegurar importación del proyecto
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.api.main import app, get_db


# ==============================================================================
# Datos Falsos para Testing (Fixtures)
# ==============================================================================

MOCK_EVENTS = [
    {
        "id": "us7000m8v1",
        "time": datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc),
        "updated": datetime(2026, 11, 8, 12, 10, 0, tzinfo=timezone.utc),
        "mag": 5.8,
        "mag_type": "mww",
        "place": "70 km W of Illapel, Chile",
        "longitude": -71.8,
        "latitude": -31.6,
        "depth": 35.0,
        "country_id": "CHL",
        "country_name": "Chile",
        "continent": "South America",
        "subregion": "South America",
        "status": "reviewed",
        "tsunami": 0,
        "sig": 512,
        "mode": "live",
        "time_epoch_ms": 1794139200000,
        "updated_epoch_ms": 1794139800000,
    },
    {
        "id": "us7000m8v2",
        "time": datetime(2026, 11, 8, 13, 30, 0, tzinfo=timezone.utc),
        "updated": datetime(2026, 11, 8, 13, 35, 0, tzinfo=timezone.utc),
        "mag": 3.4,
        "mag_type": "ml",
        "place": "15 km ENE of Granada, Spain",
        "longitude": -3.5,
        "latitude": 37.2,
        "depth": 10.0,
        "country_id": "ESP",
        "country_name": "España",
        "continent": "Europe",
        "subregion": "Southern Europe",
        "status": "automatic",
        "tsunami": 0,
        "sig": 180,
        "mode": "live",
        "time_epoch_ms": 1794144600000,
        "updated_epoch_ms": 1794144900000,
    },
    {
        "id": "us7000m8v3",
        "time": datetime(2026, 11, 8, 14, 15, 0, tzinfo=timezone.utc),
        "updated": datetime(2026, 11, 8, 14, 20, 0, tzinfo=timezone.utc),
        "mag": 7.2,
        "mag_type": "mwb",
        "place": "Fiji Islands Region",
        "longitude": 178.5,
        "latitude": -18.2,
        "depth": 550.0,
        "country_id": "FJI",
        "country_name": "Fiyi",
        "continent": "Oceania",
        "subregion": "Melanesia",
        "status": "reviewed",
        "tsunami": 1,
        "sig": 820,
        "mode": "live",
        "time_epoch_ms": 1794147300000,
        "updated_epoch_ms": 1794147600000,
    },
    {
        "id": "us7000m8v4",
        "time": datetime(2026, 11, 8, 15, 0, 0, tzinfo=timezone.utc),
        "updated": datetime(2026, 11, 8, 15, 5, 0, tzinfo=timezone.utc),
        "mag": None,
        "mag_type": None,
        "place": "Mid-Atlantic Ridge",
        "longitude": -28.0,
        "latitude": 0.5,
        "depth": None,
        "country_id": None,
        "country_name": "Sin país asignado",
        "continent": None,
        "subregion": None,
        "status": "automatic",
        "tsunami": 0,
        "sig": 50,
        "mode": "replay",
        "time_epoch_ms": 1794150000000,
        "updated_epoch_ms": 1794150300000,
    },
]

MOCK_COUNTRIES = [
    {
        "code": "CHL",
        "name_es": "Chile",
        "admin": "Chile",
        "continent": "South America",
        "subregion": "South America",
    },
    {
        "code": "ESP",
        "name_es": "España",
        "admin": "Spain",
        "continent": "Europe",
        "subregion": "Southern Europe",
    },
    {
        "code": "FJI",
        "name_es": "Fiyi",
        "admin": "Fiji",
        "continent": "Oceania",
        "subregion": "Melanesia",
    },
]


# ==============================================================================
# Clases Mocks para Base de Datos Asíncrona
# ==============================================================================

class MockAsyncCursor:
    """Cursor simulado que responde a las consultas SQL del API según la lógica de datos."""

    def __init__(self, events: List[Dict[str, Any]], countries: List[Dict[str, Any]]):
        self.events = events
        self.countries = countries
        self._last_result: Any = None

    async def execute(self, query: str, params: Optional[Dict[str, Any]] = None) -> None:
        params = params or {}
        q = query.strip()

        # 1. Comprobación de salud básica: SELECT 1;
        if "SELECT 1" in q:
            self._last_result = [{"?column?": 1}]
            return

        # 2. SELECT MAX(ingested_at)
        if "SELECT MAX(ingested_at)" in q:
            self._last_result = [{"max_ingested": datetime(2026, 11, 8, 15, 10, 0, tzinfo=timezone.utc)}]
            return

        # 3. SELECT code, name_es FROM paises
        if "FROM paises" in q:
            self._last_result = list(self.countries)
            return

        # 4. Estadísticas: conteo 2025
        if "EXTRACT(YEAR FROM time) = 2025" in q:
            self._last_result = [{"c": 15}]
            return

        # Filtrado de eventos en memoria según parámetros
        filtered = list(self.events)
        if "time >= %(desde)s" in q and "desde" in params:
            filtered = [e for e in filtered if e["time"] >= params["desde"]]
        if "time < %(hasta)s" in q and "hasta" in params:
            filtered = [e for e in filtered if e["time"] < params["hasta"]]
        if "mag >= %(min_mag)s" in q and "min_mag" in params:
            filtered = [e for e in filtered if e["mag"] is not None and e["mag"] >= params["min_mag"]]
        if "country_id = %(pais)s" in q and "pais" in params:
            filtered = [e for e in filtered if e.get("country_id") == params["pais"]]
        if "country_id IS NULL" in q:
            filtered = [e for e in filtered if e.get("country_id") is None]
        if "mode = %(modo)s" in q and "modo" in params:
            filtered = [e for e in filtered if e.get("mode") == params["modo"]]

        # 5. COUNT(*) en v_eventos_api
        if "SELECT COUNT(*) AS total FROM v_eventos_api" in q:
            self._last_result = [{"total": len(filtered)}]
            return

        # 6. Agregaciones globales de /api/estadisticas
        if "mag_menor_3" in q:
            mags = [e["mag"] for e in filtered if e["mag"] is not None]
            avg_mag = round(sum(mags) / len(mags), 2) if mags else None
            m_menor_3 = sum(1 for m in mags if m < 3.0)
            m_3_a_45 = sum(1 for m in mags if 3.0 <= m < 4.5)
            m_45_a_6 = sum(1 for m in mags if 4.5 <= m < 6.0)
            m_ge_6 = sum(1 for m in mags if m >= 6.0)
            m_sin_valor = sum(1 for e in filtered if e["mag"] is None)

            depths = [e["depth"] for e in filtered if e["depth"] is not None]
            d_someros = sum(1 for d in depths if d < 70.0)
            d_intermedios = sum(1 for d in depths if 70.0 <= d < 300.0)
            d_profundos = sum(1 for d in depths if d >= 300.0)
            d_sin_valor = sum(1 for e in filtered if e["depth"] is None)

            self._last_result = [{
                "total_eventos": len(filtered),
                "mag_promedio": avg_mag,
                "mag_menor_3": m_menor_3,
                "mag_3_a_4_5": m_3_a_45,
                "mag_4_5_a_6": m_45_a_6,
                "mag_mayor_igual_6": m_ge_6,
                "mag_sin_valor": m_sin_valor,
                "depth_someros_0_70": d_someros,
                "depth_intermedios_70_300": d_intermedios,
                "depth_profundos_mas_300": d_profundos,
                "depth_sin_valor": d_sin_valor,
            }]
            return

        # 7. Sismo máximo
        if "ORDER BY mag DESC, time DESC" in q:
            mags_events = [e for e in filtered if e["mag"] is not None]
            if mags_events:
                best = max(mags_events, key=lambda e: e["mag"])
                self._last_result = [best]
            else:
                self._last_result = []
            return

        # 8. Ventanas horarias fijas de 1h UTC
        if "DATE_TRUNC('hour', time) AS hora_utc" in q:
            hours: Dict[str, List[float]] = {}
            for e in filtered:
                h_str = e["time"].strftime("%Y-%m-%dT%H:00:00+00:00")
                if h_str not in hours:
                    hours[h_str] = []
                if e["mag"] is not None:
                    hours[h_str].append(e["mag"])

            rows = []
            for h, ms in sorted(hours.items()):
                rows.append({
                    "hora_utc": datetime.fromisoformat(h),
                    "recuento": len(ms) or 1,
                    "mag_promedio": round(sum(ms) / len(ms), 2) if ms else None,
                    "mag_maxima": max(ms) if ms else None,
                })
            self._last_result = rows
            return

        # 9. Top países
        if "GROUP BY country_id, country_name" in q:
            counts: Dict[str, Dict[str, Any]] = {}
            for e in filtered:
                c_id = e.get("country_id")
                if c_id:
                    if c_id not in counts:
                        counts[c_id] = {"pais_codigo": c_id, "pais_nombre": e["country_name"], "recuento": 0}
                    counts[c_id]["recuento"] += 1
            rows = sorted(counts.values(), key=lambda x: x["recuento"], reverse=True)[:10]
            self._last_result = rows
            return

        # 10. Consulta paginada de eventos para /api/eventos
        if "FROM v_eventos_api" in q:
            limite = params.get("limite", 500)
            offset = params.get("offset", 0)
            paged = filtered[offset : offset + limite]
            self._last_result = paged
            return

        self._last_result = []

    async def fetchone(self) -> Optional[Dict[str, Any]]:
        if isinstance(self._last_result, list):
            return self._last_result[0] if self._last_result else None
        return self._last_result

    async def fetchall(self) -> List[Dict[str, Any]]:
        if isinstance(self._last_result, list):
            return self._last_result
        return [self._last_result] if self._last_result else []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MockAsyncConnection:
    """Conexión simulada que provee el cursor."""

    def __init__(self, events: List[Dict[str, Any]], countries: List[Dict[str, Any]]):
        self.events = events
        self.countries = countries

    def cursor(self):
        return MockAsyncCursor(self.events, self.countries)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MockAsyncPool:
    """Pool simulado para el estado de la aplicación."""

    def __init__(self, events: List[Dict[str, Any]], countries: List[Dict[str, Any]], fail: bool = False):
        self.events = events
        self.countries = countries
        self.fail = fail

    def connection(self, timeout: float = 5.0):
        if self.fail:
            raise Exception("Fallo de conexión forzado para testing")
        return MockAsyncConnection(self.events, self.countries)

    async def close(self):
        pass


# ==============================================================================
# Suite de Pruebas Unitarias
# ==============================================================================

class TestObservatorioApi(unittest.IsolatedAsyncioTestCase):
    """Casos de prueba para verificar los endpoints de la API REST."""

    async def asyncSetUp(self) -> None:
        self.mock_conn = MockAsyncConnection(MOCK_EVENTS, MOCK_COUNTRIES)
        self.mock_pool = MockAsyncPool(MOCK_EVENTS, MOCK_COUNTRIES, fail=False)
        app.state.pool = self.mock_pool

        async def override_get_db():
            yield self.mock_conn

        app.dependency_overrides[get_db] = override_get_db
        self.transport = ASGITransport(app=app)

    async def asyncTearDown(self) -> None:
        app.dependency_overrides.clear()

    async def test_salud_endpoint_ok(self):
        """Verifica que /api/salud devuelva 200 con bd_conectada: true cuando la BD responde."""
        async with AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get("/api/salud")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["estado"], "ok")
        self.assertEqual(data["version"], "1.0.0")
        self.assertTrue(data["bd_conectada"])
        self.assertIn("timestamp", data)
        self.assertIn("ultima_ingesta", data)

    async def test_salud_endpoint_db_failure(self):
        """Verifica que /api/salud maneje el fallo de base de datos retornando 503 con diagnóstico."""
        app.state.pool = MockAsyncPool([], [], fail=True)
        async with AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get("/api/salud")

        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data["estado"], "error")
        self.assertFalse(data["bd_conectada"])

    async def test_eventos_geojson_contract(self):
        """Verifica el cumplimiento estricto del formato GeoJSON RFC 7946 y CONTRATO-API.md."""
        async with AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get("/api/eventos?modo=replay")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # 1. Validación de estructura raíz FeatureCollection
        self.assertEqual(data["type"], "FeatureCollection")
        self.assertIn("metadata", data)
        self.assertIn("features", data)

        # 2. Validación de metadatos requeridos
        meta = data["metadata"]
        self.assertIn("total", meta)
        self.assertIn("count", meta)
        self.assertIn("limite", meta)
        self.assertIn("offset", meta)
        self.assertIn("generated", meta)
        self.assertGreater(meta["generated"], 0)
        self.assertFalse(meta["truncated"])

        # 3. Validación de cada Feature
        features = data["features"]
        self.assertGreaterEqual(len(features), 1)
        first = features[0]
        self.assertEqual(first["type"], "Feature")
        self.assertIn("id", first)
        self.assertIn("geometry", first)
        self.assertEqual(first["geometry"]["type"], "Point")

        # Coordenadas en orden estricto [longitud, latitud, profundidad]
        coords = first["geometry"]["coordinates"]
        self.assertEqual(len(coords), 3)
        self.assertEqual(coords[0], -28.0)  # lon
        self.assertEqual(coords[1], 0.5)   # lat
        self.assertIsNone(coords[2])       # depth nula soportada sin error

        # Propiedades requeridas
        props = first["properties"]
        self.assertIn("id", props)
        self.assertIn("time", props)
        self.assertIn("place", props)
        self.assertEqual(props["country_name"], "Sin país asignado")

    async def test_eventos_filtering_by_country_and_magnitude(self):
        """Verifica que los filtros de país y magnitud mínima operen con precisión."""
        async with AsyncClient(transport=self.transport, base_url="http://test") as client:
            # Filtrar por país Chile (CHL)
            resp_chl = await client.get("/api/eventos?pais=CHL&modo=live")
            self.assertEqual(resp_chl.status_code, 200)
            data_chl = resp_chl.json()
            self.assertEqual(data_chl["metadata"]["total"], 1)
            self.assertEqual(data_chl["features"][0]["properties"]["country_id"], "CHL")

            # Filtrar por magnitud mínima 6.0
            resp_mag = await client.get("/api/eventos?min_magnitud=6.0&modo=live")
            self.assertEqual(resp_mag.status_code, 200)
            data_mag = resp_mag.json()
            self.assertEqual(data_mag["metadata"]["total"], 1)
            self.assertEqual(data_mag["features"][0]["properties"]["mag"], 7.2)

    async def test_estadisticas_endpoint(self):
        """Verifica las agregaciones analíticas, distribuciones y top países."""
        async with AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get("/api/estadisticas?modo=live")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["total_eventos"], 3)
        self.assertIsNotNone(data["mag_promedio"])
        self.assertEqual(data["max_magnitud"]["mag"], 7.2)
        self.assertEqual(data["max_magnitud"]["id"], "us7000m8v3")

        # Distribución por magnitud
        dist_m = data["distribucion_magnitud"]
        self.assertIn("menor_3", dist_m)
        self.assertIn("de_3_a_4_5", dist_m)
        self.assertIn("mayor_igual_6", dist_m)
        self.assertEqual(dist_m["mayor_igual_6"], 1)

        # Distribución por profundidad
        dist_p = data["distribucion_profundidad"]
        self.assertIn("someros_0_70km", dist_p)
        self.assertIn("profundos_mas_300km", dist_p)
        self.assertEqual(dist_p["profundos_mas_300km"], 1)

        # Ventanas horarias y top países
        self.assertGreater(len(data["ventanas_horarias"]), 0)
        self.assertGreater(len(data["top_paises"]), 0)
        self.assertIn("comparativa_historico", data)
        self.assertIn("metadata", data)

    async def test_paises_endpoint(self):
        """Verifica que el catálogo de países retorne la lista con nombres en español."""
        async with AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get("/api/paises")

        self.assertEqual(response.status_code, 200)
        countries = response.json()
        self.assertIsInstance(countries, list)
        self.assertEqual(len(countries), 3)
        self.assertIn(countries[0]["code"], ("CHL", "ESP", "FJI"))
        self.assertIn("name_es", countries[0])
        self.assertIn("admin", countries[0])

    async def test_cors_and_ngrok_headers(self):
        """Verifica soporte para CORS (localhost y Netlify) y cabecera ngrok-skip-browser-warning."""
        async with AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get(
                "/api/salud",
                headers={"Origin": "https://sismos-demo.netlify.app", "ngrok-skip-browser-warning": "1"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("access-control-allow-origin", response.headers)
        self.assertEqual(response.headers["access-control-allow-origin"], "https://sismos-demo.netlify.app")
        self.assertIn("ngrok-skip-browser-warning", response.headers)

    async def test_invalid_date_format_422(self):
        """Verifica que una fecha con formato corrupto sea rechazada con HTTP 422 descriptivo."""
        async with AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get("/api/eventos?desde=fecha-invalida-xyz")

        self.assertEqual(response.status_code, 422)
        self.assertIn("Formato de fecha inválido", response.text)

    async def test_eventos_empty_database(self):
        """Verifica que sin eventos devuelva FeatureCollection vacía (features: []) con HTTP 200."""
        empty_conn = MockAsyncConnection([], MOCK_COUNTRIES)
        async def override_empty_db():
            yield empty_conn
        app.dependency_overrides[get_db] = override_empty_db

        async with AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get("/api/eventos?modo=replay")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["type"], "FeatureCollection")
        self.assertEqual(data["features"], [])
        self.assertEqual(data["metadata"]["total"], 0)
        self.assertEqual(data["metadata"]["count"], 0)
        self.assertFalse(data["metadata"]["truncated"])

    async def test_eventos_pagination_and_truncation(self):
        """Verifica paginación con limite y offset y cálculo de truncated flag."""
        async with AsyncClient(transport=self.transport, base_url="http://test") as client:
            # Solicitar limite=1 con offset=0 sobre eventos live (3 eventos disponibles)
            response = await client.get("/api/eventos?modo=live&limite=1&offset=0")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["features"]), 1)
        self.assertEqual(data["metadata"]["count"], 1)
        self.assertEqual(data["metadata"]["limite"], 1)
        self.assertEqual(data["metadata"]["offset"], 0)
        self.assertEqual(data["metadata"]["total"], 3)
        self.assertTrue(data["metadata"]["truncated"])

    async def test_eventos_english_param_aliases(self):
        """Verifica que los alias en inglés (start, end, min_mag, country_id, limit, mode) funcionen igual."""
        async with AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.get("/api/eventos?country_id=ESP&min_mag=3.0&mode=live&limit=10")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["metadata"]["total"], 1)
        self.assertEqual(data["features"][0]["properties"]["country_id"], "ESP")

    async def test_openapi_documentation_accessible(self):
        """Verifica que la especificación OpenAPI (/openapi.json) y Swagger (/docs) estén accesibles."""
        async with AsyncClient(transport=self.transport, base_url="http://test") as client:
            res_json = await client.get("/openapi.json")
            res_docs = await client.get("/docs")

        self.assertEqual(res_json.status_code, 200)
        schema = res_json.json()
        self.assertIn("paths", schema)
        self.assertIn("/api/salud", schema["paths"])
        self.assertIn("/api/eventos", schema["paths"])
        self.assertIn("/api/estadisticas", schema["paths"])
        self.assertIn("/api/paises", schema["paths"])
        self.assertEqual(res_docs.status_code, 200)

    async def test_cors_preflight_options(self):
        """Verifica preflight CORS (OPTIONS) para orígenes autorizados como Netlify y localhost."""
        async with AsyncClient(transport=self.transport, base_url="http://test") as client:
            response = await client.options(
                "/api/eventos",
                headers={
                    "Origin": "http://localhost:4200",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "ngrok-skip-browser-warning",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("access-control-allow-origin", response.headers)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:4200")


if __name__ == "__main__":
    unittest.main()
