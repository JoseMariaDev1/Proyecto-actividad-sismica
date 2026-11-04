# Referencia detallada de campos USGS

## Tipos de magnitud (magType)

| magType | Nombre completo              | Rango típico | Notas                          |
|---------|------------------------------|--------------|--------------------------------|
| `ml`    | Local (Richter)              | -1 a 6       | Sismos locales                 |
| `md`    | Duración                     | -1 a 5       | Basada en duración de la señal |
| `mb`    | Body wave                    | 3 a 7        | Teleseísmos                    |
| `mww`   | Moment (W-phase)             | 5 a 9.5      | Grandes terremotos             |
| `mw`    | Moment                       | 3 a 9.5      | Estándar moderno               |
| `ms`    | Surface wave                 | 5 a 8.5      | Sismos someros grandes         |
| `mb_lg` | Short-period surface wave    | 3 a 7        | Regional                       |

## Tipos de evento (properties.type)

| type               | ¿Es terremoto? | Acción        |
|--------------------|:--------------:|---------------|
| `earthquake`       | ✅ Sí          | Procesar      |
| `quarry blast`     | ❌ No          | Excluir       |
| `explosion`        | ❌ No          | Excluir       |
| `ice quake`        | ❌ No          | Excluir       |
| `mining explosion` | ❌ No          | Excluir       |
| `sonic boom`       | ❌ No          | Excluir       |
| `chemical explosion`| ❌ No         | Excluir       |
| `nuclear explosion`| ❌ No          | Excluir       |
| `other event`      | ❌ No          | Excluir       |

## Campos opcionales (pueden ser null)

- `felt` (int): Número de respuestas "Did You Feel It?"
- `cdi` (float): Intensidad comunal máxima (DYFI)
- `mmi` (float): Intensidad instrumental máxima (ShakeMap)
- `alert` (string): Nivel de alerta PAGER: `green`, `yellow`, `orange`, `red`
- `tsunami` (int): 1 si se generó alerta de tsunami
- `sig` (int): Significancia (0-1000+), combina magnitud, impacto, sentido
- `nst` (int): Número de estaciones sísmicas usadas
- `dmin` (float): Distancia horizontal al epicentro más cercano (grados)
- `rms` (float): Error cuadrático medio del ajuste de viaje (segundos)
- `gap` (float): Mayor brecha azimutal entre estaciones (grados)

## Frecuencias de actualización del feed

| Feed                    | URL path                        | Actualización |
|-------------------------|---------------------------------|---------------|
| Todos, última hora      | `summary/all_hour.geojson`      | ~1 min        |
| Todos, último día       | `summary/all_day.geojson`       | ~1 min        |
| Todos, última semana    | `summary/all_week.geojson`      | ~1 min        |
| Todos, último mes       | `summary/all_month.geojson`     | ~15 min       |
| M1+, último día         | `summary/1.0_day.geojson`       | ~1 min        |
| M2.5+, último día       | `summary/2.5_day.geojson`       | ~1 min        |
| M4.5+, último día       | `summary/4.5_day.geojson`       | ~1 min        |
| Significativos, día     | `summary/significant_day.geojson`| ~1 min       |

Para el proyecto usamos `all_day.geojson` que incluye TODOS los tipos y magnitudes.
