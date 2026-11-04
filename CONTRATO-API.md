# Contrato mínimo de la API

## GET /api/eventos

Devuelve HTTP 200, `Content-Type: application/json` y un GeoJSON `FeatureCollection`. Sin eventos: `features: []`, no un error. Cada evento aparece una sola vez, con su versión actual. Por defecto devuelve terremotos ocurridos en las últimas 24 horas.

```json
{
  "type": "FeatureCollection",
  "metadata": {
    "generated": 1793113200000,
    "last_ingestion": 1793113140000,
    "mode": "live",
    "count": 1,
    "truncated": false
  },
  "features": [{
    "type": "Feature",
    "id": "ejemplo-ficticio",
    "geometry": {"type": "Point", "coordinates": [-3.7, 40.4, 12]},
    "properties": {
      "mag": 3.2,
      "magType": "ml",
      "place": "Ejemplo ficticio",
      "time": 1793109600000,
      "updated": 1793110000000,
      "country_id": "ESP",
      "country_name": "España"
    }
  }]
}
```

`generated`: generación de esta respuesta; no implica que la ingesta siga activa. `last_ingestion`: última consulta correcta a USGS. Fechas en milisegundos Unix UTC. Coordenadas en orden longitud, latitud, profundidad (km). Usa `null`, nunca NaN/Infinity, para magnitud, profundidad o país desconocidos. Geometría válida obligatoria en este endpoint.

Filtros a implementar: `start` (ISO8601, inclusive), `end` (ISO8601, exclusive), `min_mag` y `country_id`. El mapa inicial aún no envía filtros; corresponde al alumnado añadirlos. La magnitud nula no cumple un filtro `min_mag` y debe contabilizarse por separado.

Para limitar el tamaño, la API puede aplicar un máximo documentado de puntos. Si trunca, debe indicar `truncated: true`, el total completo y un mecanismo de paginación. El panel final deberá mostrarlo y no calcular estadísticas globales sobre una muestra truncada. El componente inicial espera una colección pequeña y completa.

## Otros endpoints a implementar

| Ruta | Resultado |
|---|---|
| GET /api/salud | Estado API y fecha de última ingesta; no credenciales |
| GET /api/estadisticas | Conteos por hora UTC/país, distribuciones y comparación histórica |

Los filtros de estadísticas deben equivaler a los del mapa. Cada resultado debe indicar periodo, filtros, unidad y registros sin valor. Si la base falla, devuelve un error explícito; no cero eventos como si fuera un resultado válido.

## Acceso desde Netlify

Configura CORS en FastAPI para el origen exacto de la web y `http://localhost:4200` durante desarrollo; métodos GET y OPTIONS, y cabecera `ngrok-skip-browser-warning`. Si utilizas `CORSMiddleware`, este middleware atiende el preflight. No necesitas cookies para una API pública de consulta de estos datos.

El encabezado de ngrok evita su página intermedia cuando es aplicable; no autentica al usuario. No incluir secretos en config.json. Añade timeout y manejo de errores en el frontend.

## Transporte y contenedores

La API es un servicio Docker, igual que productor, consumidor, Kafka y PostgreSQL. Uvicorn escucha en `0.0.0.0:8000`. ngrok termina el HTTPS público y gestiona el certificado; la API recibe HTTP local. El frontend utiliza la URL HTTPS del túnel. Desde otro contenedor de la misma red, el agente se conecta a `http://api:8000`; desde el host, al puerto publicado.
