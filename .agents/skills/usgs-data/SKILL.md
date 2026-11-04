---
name: usgs-data
description: >-
  Conocimiento experto sobre la API de terremotos del USGS (United States
  Geological Survey). Usar cuando se trabaje con extracción de datos sísmicos,
  feeds GeoJSON de USGS, validación de campos de terremotos, o construcción
  del productor Kafka que consulta el feed.
---

# USGS Earthquake Data — Guía de extracción

## 1. Endpoints principales

### 1.1 Feed en tiempo real (datos recientes)

```
GET https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson
```

- **Ventana móvil** de las últimas 24 horas, actualizada cada ~60 segundos.
- Devuelve **TODA** la ventana en cada respuesta (no es incremental).
- No es el "día natural anterior" ni una conexión push/WebSocket.
- Formato: GeoJSON `FeatureCollection`.

### 1.2 Catálogo histórico (búsqueda parametrizada)

```
GET https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson
    &starttime=2025-01-01T00:00:00Z
    &endtime=2025-02-01T00:00:00Z
    &minmagnitude=4
    &eventtype=earthquake
    &orderby=time-asc
```

- Límite: **20.000 resultados** por consulta. Si se excede, subdividir el
  intervalo temporal.
- Usar para descargar el histórico de 2025 (M ≥ 4.0), mes a mes.
- Los extremos temporales pueden ser inclusivos: **deduplicar** eventos
  compartidos entre intervalos adyacentes.

---

## 2. Estructura de un evento (Feature)

Cada feature del GeoJSON tiene esta estructura:

```json
{
  "type": "Feature",
  "id": "us7000nn1a",
  "properties": {
    "mag": 5.2,
    "place": "45km NNE of Hihifo, Tonga",
    "time": 1704067200000,
    "updated": 1704153600000,
    "tz": null,
    "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000nn1a",
    "detail": "...",
    "felt": null,
    "cdi": null,
    "mmi": null,
    "alert": null,
    "status": "reviewed",
    "tsunami": 0,
    "sig": 416,
    "net": "us",
    "code": "7000nn1a",
    "ids": ",us7000nn1a,",
    "sources": ",us,",
    "types": ",origin,phase-data,",
    "nst": 78,
    "dmin": 2.345,
    "rms": 0.89,
    "gap": 42,
    "magType": "mww",
    "type": "earthquake",
    "title": "M 5.2 - 45km NNE of Hihifo, Tonga"
  },
  "geometry": {
    "type": "Point",
    "coordinates": [-175.1234, -15.6789, 10.0]
  }
}
```

### 2.1 Campos obligatorios para el proyecto

| Campo                    | Tipo     | Descripción                                       | Puede ser null |
|--------------------------|----------|---------------------------------------------------|----------------|
| `id`                     | string   | Identificador único del evento                    | No             |
| `properties.time`        | integer  | Milisegundos desde Unix epoch (UTC)               | No             |
| `properties.updated`     | integer  | Última revisión USGS, ms desde epoch              | No             |
| `properties.mag`         | float    | Magnitud (puede ser negativa en microsismos)      | **Sí**         |
| `properties.magType`     | string   | Tipo de magnitud (ml, mb, mww, md…)               | **Sí**         |
| `properties.type`        | string   | Tipo de evento: `earthquake`, `quarry blast`, etc. | No             |
| `properties.place`       | string   | Descripción textual de ubicación (NO usar para geocoding) | **Sí**  |
| `geometry.coordinates`   | array    | `[longitud, latitud, profundidad_km]`             | No             |

### 2.2 Coordenadas

- Orden: **[longitud, latitud, profundidad]** (¡NO lat/lon!)
- Longitud: -180 a 180
- Latitud: -90 a 90
- Profundidad: en km. **Puede ser negativa** (evento por encima del nivel del
  mar, e.g., volcán). No rechazar automáticamente.

### 2.3 Tiempos

- Todos los tiempos son **milisegundos** desde Unix epoch (1970-01-01T00:00:00Z).
- Convertir a `datetime` UTC: `datetime.fromtimestamp(ms / 1000, tz=timezone.utc)`
- Separar siempre:
  - `event_time` → cuándo ocurrió el terremoto (`properties.time`)
  - `updated_at` → cuándo USGS actualizó el registro (`properties.updated`)
  - `ingested_at` → cuándo nuestro sistema lo procesó (generado por nosotros)

---

## 3. Reglas de filtrado

### 3.1 Solo terremotos
```python
if event["properties"]["type"] != "earthquake":
    # Registrar motivo de exclusión y conservar el evento aparte
    log.info(f"Excluido {event['id']}: type={event['properties']['type']}")
    continue
```

Tipos que NO son terremotos: `quarry blast`, `explosion`, `ice quake`,
`mining explosion`, `sonic boom`, `chemical explosion`, etc.

### 3.2 Magnitud
- Magnitudes **negativas son válidas** (microsismos de M -1 a M 0).
- Magnitud **null** → conservar el evento, marcar campo como incompleto.
- NO rellenar nulos con 0.0 (falsearía el dato).

### 3.3 Profundidad
- Profundidad **negativa es válida** (evento sobre nivel del mar).
- Profundidad **null** → rarísimo, marcar como incompleto.

---

## 4. Deduplicación y versionado

### 4.1 Lógica del productor (estado persistente)

```
Para cada evento del feed:
  1. Si event.id NO existe en estado → NUEVO → publicar a Kafka
  2. Si event.id existe Y event.updated > estado[id].updated → REVISIÓN → publicar
  3. Si event.id existe Y event.updated <= estado[id].updated → YA PROCESADO → omitir
```

### 4.2 Clave Kafka
- Usar `event.id` como clave del mensaje Kafka.
- Garantiza que todas las versiones del mismo evento van a la misma partición.

### 4.3 Campos del mensaje Kafka

```json
{
  "source": "usgs_feed",
  "ingested_at": "2025-06-15T10:30:00Z",
  "mode": "live",
  "event": { ... }
}
```

- `mode`: `"live"` para el feed en tiempo real, `"replay"` para reproducir histórico.

### 4.4 Evento desaparecido del feed
- Que un evento NO aparezca en la siguiente consulta **no significa que USGS lo
  haya eliminado**: simplemente ha envejecido más allá de las 24h.
- NUNCA borrar eventos del almacenamiento porque desaparezcan del feed.

---

## 5. Manejo de errores

### 5.1 Errores HTTP
| Código | Acción |
|--------|--------|
| 200    | Procesar normalmente |
| 204    | Sin contenido, reintentar después del intervalo |
| 429    | Rate limit: espera progresiva (backoff exponencial) |
| 5xx    | Error del servidor: reintentar con backoff |
| Timeout| Reintentar con backoff, máximo 3 intentos |

### 5.2 Backoff exponencial
```python
import asyncio
import random

async def fetch_with_retry(url, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = await client.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
            if attempt == max_retries - 1:
                raise
            wait = (2 ** attempt) + random.uniform(0, 1)
            log.warning(f"Intento {attempt+1} fallido: {e}. Reintento en {wait:.1f}s")
            await asyncio.sleep(wait)
```

### 5.3 JSON inválido
- Si la respuesta no es JSON válido → log de error, NO borrar estado anterior.

---

## 6. Recuperación tras parada larga

Si el productor estuvo parado más de 24 horas:
1. El feed solo contiene las últimas 24h → hay un hueco de datos.
2. Usar el **catálogo histórico** (endpoint de búsqueda) para rellenar el
   intervalo perdido, con `starttime` y `endtime` ajustados.
3. Publicar esos eventos con `mode: "replay"` para distinguirlos.
4. Documentar esta limitación en la memoria.

---

## 7. Verificación rápida

Para verificar que la extracción funciona, ejecutar:

```bash
curl -s "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson" | python -m json.tool | head -50
```

Debe devolver un `FeatureCollection` con `metadata.count` indicando el número
de eventos y un array `features` con los terremotos.
