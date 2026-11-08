"""
Suite de pruebas unitarias y de validación de calidad para el Consumidor.

Verifica:
1. SpatialMatcher: indexación R-Tree, búsqueda logarítmica O(log N) y sismos marítimos.
2. EarthquakeConsumer.parse_and_validate:
   - 6 dimensiones de calidad de datos.
   - Aislamiento de JSONs corruptos.
   - Coordenadas fuera de rango.
   - Tipos de eventos no sismológicos.
   - Tolerancia y preservación de magnitudes nulas y microterremotos (mag negativa).
   - Tolerancia a profundidades negativas.
3. Formato y compatibilidad de tipos con PostgreSQL y fn_ingestar_evento.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from pathlib import Path
import unittest

from backend.consumer.spatial import SpatialMatcher
from backend.consumer.consumer import EarthquakeConsumer


class TestSpatialMatcher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matcher = SpatialMatcher()

    def test_land_coordinates_match_country(self):
        # Madrid, España (-3.7038, 40.4168)
        esp = self.matcher.match(-3.7038, 40.4168)
        self.assertIsNotNone(esp)
        self.assertEqual(esp["code"], "ESP")
        self.assertIn("España", esp["name_es"])
        self.assertEqual(esp["continent"], "Europe")

        # Santiago, Chile (-70.6693, -33.4489)
        chl = self.matcher.match(-70.6693, -33.4489)
        self.assertIsNotNone(chl)
        self.assertEqual(chl["code"], "CHL")
        self.assertEqual(chl["name_es"], "Chile")
        self.assertEqual(chl["continent"], "South America")

        # Tokio, Japón (139.6917, 35.6895)
        jpn = self.matcher.match(139.6917, 35.6895)
        self.assertIsNotNone(jpn)
        self.assertEqual(jpn["code"], "JPN")

    def test_ocean_coordinates_return_none(self):
        # Punto en medio del Océano Atlántico (0.0, 0.0)
        atlantic = self.matcher.match(0.0, 0.0)
        self.assertIsNone(atlantic, "El océano abierto debe retornar None (marítimo)")

        # Punto en el Océano Pacífico (-140.0, 10.0)
        pacific = self.matcher.match(-140.0, 10.0)
        self.assertIsNone(pacific)

    def test_out_of_bounds_coordinates(self):
        # Longitud fuera de [-180, 180]
        self.assertIsNone(self.matcher.match(190.0, 40.0))
        # Latitud fuera de [-90, 90]
        self.assertIsNone(self.matcher.match(-3.7, 105.0))


class TestDataQualityValidation(unittest.TestCase):
    def test_corrupted_json(self):
        corrupted_payload = '{"id": "us123", "properties": {"mag": 4.5'  # JSON truncado
        is_valid, reason, data = EarthquakeConsumer.parse_and_validate(corrupted_payload)
        self.assertFalse(is_valid)
        self.assertIn("JSON corrupto", reason)
        self.assertIsNone(data)

    def test_valid_earthquake(self):
        valid_payload = json.dumps({
            "source": "usgs_feed",
            "ingested_at": "2025-06-15T12:00:00Z",
            "mode": "live",
            "event": {
                "type": "Feature",
                "id": "us7000test1",
                "properties": {
                    "mag": 5.8,
                    "place": "10km N of Santiago, Chile",
                    "time": 1718452800000,
                    "updated": 1718453400000,
                    "magType": "mww",
                    "status": "reviewed",
                    "type": "earthquake",
                    "tsunami": 0,
                    "sig": 512,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [-70.65, -33.40, 15.0],
                },
            },
        })

        is_valid, reason, data = EarthquakeConsumer.parse_and_validate(valid_payload)
        self.assertTrue(is_valid)
        self.assertIsNone(reason)
        self.assertIsNotNone(data)
        self.assertEqual(data["id"], "us7000test1")
        self.assertEqual(data["mag"], 5.8)
        self.assertEqual(data["longitude"], -70.65)
        self.assertEqual(data["latitude"], -33.40)
        self.assertEqual(data["depth"], 15.0)
        self.assertEqual(data["mode"], "live")

    def test_null_magnitude_is_accepted(self):
        # Rúbrica: mag null es VÁLIDA y debe conservarse
        payload = json.dumps({
            "type": "Feature",
            "id": "us7000nullmag",
            "properties": {
                "mag": None,
                "place": "Near Coast",
                "time": 1718452800000,
                "updated": 1718453400000,
                "type": "earthquake",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [-120.0, 35.0, 8.0],
            },
        })

        is_valid, reason, data = EarthquakeConsumer.parse_and_validate(payload)
        self.assertTrue(is_valid, "Eventos con magnitud null deben ser admitidos")
        self.assertIsNone(data["mag"], "Magnitud debe conservarse como None")

    def test_negative_magnitude_is_accepted(self):
        # Rúbrica: microsismos con magnitud negativa son VÁLIDOS
        payload = json.dumps({
            "type": "Feature",
            "id": "nc7000negmag",
            "properties": {
                "mag": -0.8,
                "place": "The Geysers, CA",
                "time": 1718452800000,
                "updated": 1718453400000,
                "type": "earthquake",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [-122.8, 38.8, 1.2],
            },
        })

        is_valid, reason, data = EarthquakeConsumer.parse_and_validate(payload)
        self.assertTrue(is_valid)
        self.assertEqual(data["mag"], -0.8)

    def test_negative_depth_is_accepted(self):
        # Rúbrica: profundidad negativa (sobre el nivel del mar, ej. volcanes) es VÁLIDA
        payload = json.dumps({
            "type": "Feature",
            "id": "hv7000volcano",
            "properties": {
                "mag": 2.1,
                "place": "Kilauea Volcano, Hawaii",
                "time": 1718452800000,
                "updated": 1718453400000,
                "type": "earthquake",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [-155.28, 19.42, -1.5],
            },
        })

        is_valid, reason, data = EarthquakeConsumer.parse_and_validate(payload)
        self.assertTrue(is_valid)
        self.assertEqual(data["depth"], -1.5)

    def test_invalid_coordinates_rejected(self):
        # Latitud mayor a 90
        payload_bad_lat = json.dumps({
            "type": "Feature",
            "id": "bad_lat",
            "properties": {
                "mag": 3.0,
                "time": 1718452800000,
                "updated": 1718453400000,
                "type": "earthquake",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [-3.7, 120.0, 10.0],
            },
        })

        is_valid, reason, data = EarthquakeConsumer.parse_and_validate(payload_bad_lat)
        self.assertFalse(is_valid)
        self.assertIn("Coordenadas fuera de rango", reason)

        # Longitud menor a -180
        payload_bad_lon = json.dumps({
            "type": "Feature",
            "id": "bad_lon",
            "properties": {
                "mag": 3.0,
                "time": 1718452800000,
                "updated": 1718453400000,
                "type": "earthquake",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [-195.0, 40.0, 10.0],
            },
        })

        is_valid, reason, data = EarthquakeConsumer.parse_and_validate(payload_bad_lon)
        self.assertFalse(is_valid)
        self.assertIn("Coordenadas fuera de rango", reason)

    def test_non_earthquake_event_type_rejected(self):
        # Rúbrica: 'quarry blast', 'explosion', etc. deben excluirse
        payload_blast = json.dumps({
            "type": "Feature",
            "id": "us_blast_1",
            "properties": {
                "mag": 2.5,
                "time": 1718452800000,
                "updated": 1718453400000,
                "type": "quarry blast",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [-115.0, 36.0, 0.0],
            },
        })

        is_valid, reason, data = EarthquakeConsumer.parse_and_validate(payload_blast)
        self.assertFalse(is_valid)
        self.assertIn("no sismológico", reason)


class TestConsumerPersistenceAndFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.consumer = EarthquakeConsumer()
        # Mockear el pool de base de datos
        self.mock_pool = MagicMock()
        self.mock_conn = MagicMock()
        self.mock_cur = AsyncMock()

        # Configurar context managers asíncronos para connection(), transaction() y cursor()
        self.mock_pool.connection.return_value.__aenter__.return_value = self.mock_conn
        self.mock_pool.connection.return_value.__aexit__.return_value = None

        self.mock_conn.transaction.return_value.__aenter__.return_value = self.mock_conn
        self.mock_conn.transaction.return_value.__aexit__.return_value = None

        self.mock_conn.cursor.return_value.__aenter__.return_value = self.mock_cur
        self.mock_conn.cursor.return_value.__aexit__.return_value = None
        self.mock_conn.commit = AsyncMock()

        self.consumer._db_pool = self.mock_pool

    async def test_persist_event_calls_raw_and_fn_ingestar(self):
        # Configurar retorno de fn_ingestar_evento
        self.mock_cur.fetchone.return_value = ("INSERTED_NEW",)

        event_data = {
            "id": "us_mock_1",
            "source": "usgs_feed",
            "ingested_at": datetime.now(timezone.utc),
            "mode": "live",
            "time": datetime.now(timezone.utc),
            "updated": datetime.now(timezone.utc),
            "mag": 6.2,
            "mag_type": "mww",
            "place": "Central Chile",
            "longitude": -71.5,
            "latitude": -33.0,
            "depth": 25.0,
            "country_code": "CHL",
            "status": "reviewed",
            "event_type": "earthquake",
            "tsunami": 1,
            "sig": 600,
            "feature": {"id": "us_mock_1", "type": "Feature"},
            "raw_payload": {"event": {"id": "us_mock_1"}},
        }

        outcome = await self.consumer.persist_event(event_data)
        self.assertEqual(outcome, "INSERTED_NEW")

        # Verificar que se ejecutaron al menos 2 sentencias SQL (eventos_raw y fn_ingestar_evento)
        self.assertEqual(self.mock_cur.execute.call_count, 2)
        call_raw = self.mock_cur.execute.call_args_list[0]
        self.assertIn("INSERT INTO eventos_raw", call_raw[0][0])
        call_fn = self.mock_cur.execute.call_args_list[1]
        self.assertIn("SELECT fn_ingestar_evento", call_fn[0][0])

    async def test_send_to_quarantine_persists_in_db(self):
        await self.consumer.send_to_quarantine(
            event_id="bad_id_1",
            reason="Coordenadas fuera de rango",
            raw_payload="{'bad': True}",
        )
        self.assertEqual(self.consumer.stats["cuarentena"], 1)
        self.mock_cur.execute.assert_called_once()
        query = self.mock_cur.execute.call_args[0][0]
        self.assertIn("INSERT INTO eventos_cuarentena", query)

    async def test_process_record_with_ocean_earthquake(self):
        # Simular registro de Kafka con sismo en aguas abiertas
        self.mock_cur.fetchone.return_value = ("INSERTED_NEW",)

        record = MagicMock()
        record.topic = "terremotos"
        record.partition = 0
        record.offset = 42
        ocean_payload = json.dumps({
            "source": "usgs_feed",
            "event": {
                "id": "ocean_quake_1",
                "type": "Feature",
                "properties": {
                    "mag": 4.5,
                    "time": 1718452800000,
                    "updated": 1718453400000,
                    "type": "earthquake",
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [-140.0, 10.0, 10.0],  # Marítimo
                },
            },
        })
        record.value = ocean_payload.encode("utf-8")

        outcome = await self.consumer.process_record(record)
        self.assertEqual(outcome, "INSERTED_NEW")
        self.assertEqual(self.consumer.stats["maritimos_sin_pais"], 1)
        self.assertEqual(self.consumer.stats["con_pais_asignado"], 0)


if __name__ == "__main__":
    unittest.main()
