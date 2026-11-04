# Ejemplo de respuesta del feed USGS

Este archivo muestra la estructura real de una respuesta del endpoint
`all_day.geojson` para que el agente entienda el formato sin hacer una petición.

## Respuesta completa (simplificada a 2 eventos)

```json
{
  "type": "FeatureCollection",
  "metadata": {
    "generated": 1704067260000,
    "url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson",
    "title": "USGS All Earthquakes, Past Day",
    "status": 200,
    "api": "1.14.1",
    "count": 2
  },
  "features": [
    {
      "type": "Feature",
      "id": "us7000example1",
      "properties": {
        "mag": 4.8,
        "place": "120km SSW of Constitución, Chile",
        "time": 1704060000000,
        "updated": 1704063600000,
        "tz": null,
        "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000example1",
        "detail": "https://earthquake.usgs.gov/fdsnws/event/1/query?eventid=us7000example1&format=geojson",
        "felt": 12,
        "cdi": 3.1,
        "mmi": 4.2,
        "alert": "green",
        "status": "reviewed",
        "tsunami": 0,
        "sig": 354,
        "net": "us",
        "code": "7000example1",
        "ids": ",us7000example1,",
        "sources": ",us,",
        "types": ",dyfi,moment-tensor,origin,phase-data,shakemap,",
        "nst": 92,
        "dmin": 1.234,
        "rms": 0.72,
        "gap": 38,
        "magType": "mww",
        "type": "earthquake",
        "title": "M 4.8 - 120km SSW of Constitución, Chile"
      },
      "geometry": {
        "type": "Point",
        "coordinates": [-72.5432, -36.8765, 35.0]
      }
    },
    {
      "type": "Feature",
      "id": "nc73example2",
      "properties": {
        "mag": 1.2,
        "place": "8km NW of The Geysers, CA",
        "time": 1704055000000,
        "updated": 1704056000000,
        "tz": null,
        "url": "https://earthquake.usgs.gov/earthquakes/eventpage/nc73example2",
        "detail": "https://earthquake.usgs.gov/fdsnws/event/1/query?eventid=nc73example2&format=geojson",
        "felt": null,
        "cdi": null,
        "mmi": null,
        "alert": null,
        "status": "automatic",
        "tsunami": 0,
        "sig": 22,
        "net": "nc",
        "code": "73example2",
        "ids": ",nc73example2,",
        "sources": ",nc,",
        "types": ",nearby-cities,origin,phase-data,",
        "nst": 15,
        "dmin": 0.008,
        "rms": 0.05,
        "gap": 72,
        "magType": "md",
        "type": "earthquake",
        "title": "M 1.2 - 8km NW of The Geysers, CA"
      },
      "geometry": {
        "type": "Point",
        "coordinates": [-122.8012, 38.8234, 2.1]
      }
    }
  ],
  "bbox": [-122.8012, -36.8765, 2.1, -72.5432, 38.8234, 35.0]
}
```

## Notas clave

1. `metadata.count` = número total de features en la respuesta.
2. `metadata.generated` = timestamp de cuándo USGS generó esta respuesta.
3. `bbox` = bounding box de todos los eventos: [minLon, minLat, minDepth, maxLon, maxLat, maxDepth].
4. Cada `feature.id` es el identificador único global del evento.
5. `properties.status` puede ser `"automatic"` (sin revisión humana) o `"reviewed"`.

