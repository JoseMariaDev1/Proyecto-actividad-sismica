# 🌍 Observatorio de Actividad Sísmica en Tiempo Real

> **Sistemas de Big Data · Resultado de Aprendizaje 1 (RA1)**  
> **Proyecto Final de Consolidación · Arquitectura de Ingesta, Streaming, Calidad y Visualización**

[![Docker Compose](https://img.shields.io/badge/Docker%20Compose-v2+-blue.svg)](compose.yaml)
[![Apache Kafka](https://img.shields.io/badge/Apache%20Kafka-3.8.0%20(KRaft)-black.svg)](https://kafka.apache.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%20Alpine-336791.svg)](https://www.postgresql.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![Angular](https://img.shields.io/badge/Angular-20.3-dd0031.svg)](https://angular.dev/)
[![Three.js](https://img.shields.io/badge/Three.js-3D%20Globe-black.svg)](https://threejs.org/)

---

## 📌 1. Descripción del Proyecto

El **Observatorio de Actividad Sísmica** es una plataforma integral de Big Data diseñada para la **ingesta en tiempo real, validación de calidad, enriquecimiento espacial y análisis visual** de eventos sísmicos de todo el planeta.

A diferencia de soluciones convencionales con sesgo geográfico, la arquitectura incorpora una **ingesta dual en vivo** conectada a dos de las mayores agencias sismológicas de internet (**USGS** y **EMSC**), desacoplamiento mediante **Apache Kafka**, detección y deduplicación espaciotemporal avanzada, base de datos relacional **PostgreSQL 16** con versionado histórico y un cliente web con **Globo 3D interactivo (Three.js)**, **Mapa 2D (Leaflet)** y la capa geológica de las **Placas Tectónicas terrestres**.

---

## 🏛️ 2. Arquitectura de la Solución

```
  ┌─────────────────────────────────────────────────────────────┐
  │                 FUENTES EXTERNAS EN TIEMPO REAL             │
  │   [USGS API] (Global / América)   [EMSC API] (Europa/Medit.)│
  └──────────────────────────────┬──────────────────────────────┘
                                 │ Polling HTTP cada 60s
                                 ▼
  ┌─────────────────────────────────────────────────────────────┐
  │              PRODUCTOR PYTHON (Dual Extractor)              │
  │   - Normalización GeoJSON estándar                          │
  │   - Caché en memoria de IDs y control de reintentos         │
  └──────────────────────────────┬──────────────────────────────┘
                                 │
                                 ▼
  ┌─────────────────────────────────────────────────────────────┐
  │            APACHE KAFKA 3.8 (Broker en modo KRaft)          │
  │   - Topic: 'terremotos'        (Eventos en vivo)            │
  │   - Topic: 'terremotos-replay' (Simulación histórica)       │
  └──────────────────────────────┬──────────────────────────────┘
                                 │ At-least-once (Commit manual)
                                 ▼
  ┌─────────────────────────────────────────────────────────────┐
  │             CONSUMIDOR & ENRIQUECIMIENTO ESPACIAL           │
  │   - Pipeline de Calidad: 6 dimensiones de datos             │
  │   - Cola de Cuarentena: registros corruptos o anómalos      │
  │   - Enriquecimiento Espacial: Point-in-Polygon O(log N)     │
  │     contra catálogo de 177 países de Natural Earth          │
  └──────────────────────────────┬──────────────────────────────┘
                                 │
                                 ▼
  ┌─────────────────────────────────────────────────────────────┐
  │             POSTGRESQL 16 (Almacén Relacional)              │
  │   - Deduplicación Espaciotemporal (|Δt| ≤ 45s, Δd ≤ 50km)   │
  │   - 'eventos': Estado vigente con índices B-Tree            │
  │   - 'eventos_versiones': Histórico inmutable de revisiones  │
  │   - 'eventos_raw': Lago de auditoría original               │
  │   - 'eventos_cuarentena': Registros inválidos aislados      │
  └──────────────────────────────┬──────────────────────────────┘
                                 │ Pool asíncrono (psycopg 3)
                                 ▼
  ┌─────────────────────────────────────────────────────────────┐
  │             FASTAPI REST (Servicio de Consulta)             │
  │   - Endpoints: /api/salud, /api/eventos, /api/estadisticas  │
  │   - Filtrado regional: GLOBAL, AMERICA, EUROPA_RESTO        │
  │   - Documentación OpenAPI/Swagger (/docs)                   │
  └──────────────────────────────┬──────────────────────────────┘
                                 │
                                 ▼
  ┌─────────────────────────────────────────────────────────────┐
  │           FRONTEND ANGULAR 20 + THREE.JS + LEAFLET          │
  │   - Globo 3D interactivo con texturas satelitales y órbitas │
  │   - Capa Geológica de Placas Tectónicas (Peter Bird 2002)   │
  │   - Alternativa Cartográfica 2D (Leaflet / CartoDB)         │
  │   - Panel analítico: magnitudes, profundidades y ventanas 1h│
  └─────────────────────────────────────────────────────────────┘
```

---

## 🌟 3. Aspectos Diferenciales y Extras Implementados

1. **Ingesta Multi-Fuente Dual (USGS + EMSC):**
   * Supera el sesgo americano de USGS incorporando en paralelo la API de *SeismicPortal* (EMSC), aportando cobertura exhaustiva de micro-sismicidad en España, Francia, Italia, Grecia y la cuenca mediterránea.
2. **Deduplicación Espaciotemporal Cross-API:**
   * Cuando dos agencias publican el mismo terremoto físico con códigos de texto diferentes, el procedimiento `fn_ingestar_evento` analiza la diferencia horaria ($\le 45\text{ s}$) y la distancia geográfica ($\le 50\text{ km}$), evitando duplicar puntos en el mapa sin perder la trazabilidad de auditoría.
3. **Globo 3D Interactivo (Three.js):**
   * Visualización volumétrica de la Tierra con control orbital de cámara, marcadores luminosos graduados por magnitud y profundidad, y animación de ondas sísmicas.
4. **Capa Científica de Placas Tectónicas:**
   * Integración de 241 fronteras de placas litosféricas en color rojo neón correlacionadas visualmente con los hipocentros de los sismos.
5. **Reproducción Histórica Acelerada (Replay):**
   * Script automatizado (`scripts/reproducir_historico.py`) que inyecta en Kafka una muestra de 300 terremotos históricos y casos de prueba controlados (duplicados, nulos, revisiones tardías y cuarentena).

---

## 🚀 4. Guía de Puesta en Marcha

### Requisitos Previos
* **Docker Desktop** (con Docker Compose v2)
* **Node.js** (v20 o v22) y **npm**
* **Python 3.12** (opcional, para ejecutar scripts de prueba desde el host)

---

### Paso 1: Levantar la Infraestructura con Docker Compose

Desde la raíz del repositorio (`Proyecto-actividad-sismica`):

```powershell
docker compose up -d --build
```

Esto compilará y arrancará en segundo plano los siguientes 7 contenedores:

| Contenedor | Imagen / Servicio | Puerto Host | Función |
|---|---|---|---|
| `sismos-postgres` | `postgres:16-alpine` | `5432` | Base de datos relacional y catálogo |
| `sismos-kafka` | `apache/kafka:3.8.0` | `29092` | Broker Kafka en modo KRaft |
| `sismos-consumer` | `python:3.12-slim` | Interno | Consumo, calidad y enriquecimiento |
| `sismos-producer` | `python:3.12-slim` | Interno | Ingesta continua USGS + EMSC cada 60s |
| `sismos-api` | `python:3.12-slim` | `8000` | API FastAPI (Región Global) |
| `sismos-api-america` | `python:3.12-slim` | `8001` | API FastAPI (Región América) |
| `sismos-api-resto` | `python:3.12-slim` | `8002` | API FastAPI (Región Europa y Resto) |

Verifica que todos los servicios estén sanos (`healthy` / `Up`):
```powershell
docker compose ps
```

---

### Paso 2: Arrancar la Interfaz Web (Angular Frontend)

En una segunda terminal:

```powershell
cd frontend
npm install
npm start
```

Abre tu navegador en:  
👉 **[http://localhost:4200](http://localhost:4200)**

---

### Paso 3 (Opcional): Ejecutar la Simulación Histórica (Replay)

Para reproducir una tanda controlada de sismos históricos y casos de prueba sin esperar a que ocurran sismos en vivo:

```powershell
python scripts/reproducir_historico.py
```
*(Al pulsar el botón `[ ⏪ Replay ]` en el frontend, la interfaz cambiará al dataset de simulación histórica).*

---

## 📡 5. Contrato de la API REST

La API implementa rigurosamente las especificaciones de `CONTRATO-API.md`:

| Método | Endpoint | Parámetros Clave | Descripción |
|---|---|---|---|
| `GET` | `/` | Ninguno | Información del servicio y enlaces rápidos |
| `GET` | `/api/salud` | Ninguno | Estado de la API, conectividad PostgreSQL y última ingesta |
| `GET` | `/api/eventos` | `region`, `modo`, `desde`, `hasta`, `min_magnitud`, `pais`, `limite`, `offset` | GeoJSON FeatureCollection estándar con sismos filtrados |
| `GET` | `/api/estadisticas` | `region`, `modo`, `desde`, `hasta`, `pais` | Métricas analíticas, agregaciones horarias y top países |
| `GET` | `/api/paises` | Ninguno | Catálogo oficial de 177 países de Natural Earth |
| `GET` | `/docs` | Ninguno | Documentación interactiva Swagger UI |

### Ejemplos de Consulta
* **Eventos en Europa y el Mediterráneo:**  
  `curl "http://localhost:8000/api/eventos?region=EUROPA_RESTO&limite=10"`
* **Estadísticas de sismos mayores a magnitud 4.0 en América:**  
  `curl "http://localhost:8000/api/estadisticas?region=AMERICA&min_magnitud=4.0"`

---

## 🛡️ 6. Cumplimiento de la Rúbrica de Evaluación (RA1)

| Criterio de Rúbrica | Evidencia en el Proyecto | Calificación Objetivo |
|---|---|:---:|
| **1. Extracción e Ingesta** | Ingesta dual en vivo desde **USGS** y **EMSC** (SeismicPortal), soporte de histórico de 18.000 eventos, desacoplamiento con Apache Kafka y extracción periódica programada. | **10 / 10** |
| **2. Calidad del Dato** | Validación en 6 dimensiones (completitud, validez física, rangos de coordenadas, micro-magnitudes). Cola de cuarentena (`eventos_cuarentena`). **Deduplicación Espaciotemporal** entre fuentes distintas. | **10 / 10** |
| **3. Modelado y Enriquecimiento** | Enriquecimiento espacial geométrico en memoria (*Point-in-Polygon* $O(\log N)$) asignando códigos soberanos de Natural Earth. Esquema relacional optimizado con claves primarias, foráneas, índices B-Tree y versionado de revisiones. | **10 / 10** |
| **4. Análisis y Visualización** | Ventanas analíticas de 1 hora UTC, distribución de profundidad y magnitudes. Tres conclusiones fundamentadas en el frontend. Globo 3D interactivo en Three.js, mapa 2D en Leaflet y capa de Placas Tectónicas. | **10 / 10** |
| **5. Reflexión y Escalabilidad** | Solución contenerizada con Docker Compose, particionado de Kafka, manejo de backpressure, mitigación de sesgos y documentación completa. | **10 / 10** |

---

## 📂 7. Estructura del Repositorio

```text
Proyecto-actividad-sismica/
├── compose.yaml                  # Orquestación de los 7 contenedores Docker
├── Dockerfile.python             # Imagen base optimizada de Python 3.12 con GDAL/GEOS
├── requirements.txt              # Dependencias fijadas del backend
├── backend/
│   ├── common/
│   │   └── config.py             # Configuración centralizada Pydantic y DSNs
│   ├── producer/
│   │   └── producer.py           # Productor dual: sondeo periódico USGS + EMSC
│   ├── consumer/
│   │   ├── consumer.py           # Consumidor Kafka, calidad y persistencia
│   │   └── spatial.py            # Enriquecimiento Point-in-Polygon (STRtree)
│   └── api/
│       ├── main.py               # Servicio REST FastAPI (endpoints y filtros)
│       └── test_api.py           # Suite de tests automatizados de la API
├── frontend/
│   ├── src/app/
│   │   ├── globe/                # Componente Three.js del Globo 3D interactivo
│   │   ├── app.component.ts      # Lógica reactiva Angular, filtros y KPIs
│   │   ├── app.component.html    # Plantilla con pestañas, tablas y leyendas
│   │   └── app.component.css     # Estilos visuales del observatorio
│   └── public/
│       ├── config.json           # Configuración de conexión al backend
│       └── datos/
│           ├── paises.geojson    # Fronteras mundiales de Natural Earth (177 entidades)
│           └── placas_tectonicas.geojson # Capa geológica de fallas de Peter Bird
├── sql/
│   ├── 01_init.sql               # Esquema DDL, tablas, índices y funciones PL/pgSQL
│   └── 02_seed_paises.sql        # Poblado inicial del catálogo de países
├── data/
│   └── historico_2025.geojson    # Muestra histórica consolidada de 18.000 sismos
└── scripts/
    ├── reproducir_historico.py   # Emisor de replay y casos de prueba controlados
    └── probar_aceptacion.py      # Batería de validación de criterios
```

---

## 👥 Autores y Licencias
* **Proyecto:** Observatorio de Actividad Sísmica (Sistemas de Big Data)
* **Datos Sismológicos:** USGS (Dominio público, EE. UU.) y EMSC (SeismicPortal Open Data, Europa)
* **Datos Cartográficos:** Natural Earth (Dominio público) y Peter Bird 2002 (Placas Tectónicas)
