---
name: docker-kafka-pg
description: >-
  Conocimiento experto y patrones de diseño para la infraestructura de Docker Compose
  del proyecto Observatorio Sísmico: orquestación de 5 servicios separados (PostgreSQL 16,
  Apache Kafka 3.8 en modo KRaft, Productor Python, Consumidor Python y API FastAPI),
  configuración de healthchecks, variables de entorno, redes internas y volúmenes persistentes.
---

# Docker Compose: Orquestación de Kafka KRaft, PostgreSQL y Servicios Python

Esta skill contiene las directrices de arquitectura de contenedores, parámetros de configuración y buenas prácticas exigidas por el enunciado del proyecto.

---

## 1. Arquitectura de Servicios Obligatoria

El enunciado exige **cinco servicios separados** en `compose.yaml`:

| Servicio | Imagen / Build | Puerto Expuesto | Responsabilidad | Dependencia (Healthcheck) |
|---|---|---|---|---|
| `postgres` | `postgres:16-alpine` | `5432:5432` | Almacenamiento relacional, histórico, dimensiones y cuarentena | — |
| `kafka` | `apache/kafka:3.8.0` | `9092:9092` | Broker de mensajería KRaft (sin ZooKeeper) | — |
| `consumer` | Build Python (`Dockerfile.python`) | Ninguno (red interna) | Lectura de Kafka, validación, enriquecimiento espacial y escritura en BD | Espera a `postgres` y `kafka` saludables |
| `producer` | Build Python (`Dockerfile.python`) | Ninguno (red interna) | Consulta a USGS cada 60s y publicación de eventos en Kafka | Espera a `kafka` saludable |
| `api` | Build Python (`Dockerfile.python`) | `8000:8000` | API REST FastAPI para frontend y túnel ngrok | Espera a `postgres` saludable |

> [!IMPORTANT]
> **No basta con `depends_on: [postgres, kafka]`**. El orden de arranque no garantiza que PostgreSQL admita conexiones ni que el broker Kafka haya elegido líder. Se deben usar condiciones `condition: service_healthy`.

---

## 2. Configuración de PostgreSQL 16 (`postgres`)

- **Imagen**: `postgres:16-alpine` (ligera, segura y rápida).
- **Inicialización automática**: Montar `./sql:/docker-entrypoint-initdb.d:ro`. Los ficheros `01_init.sql` y `02_seed_paises.sql` se ejecutan alfabéticamente en el primer arranque.
- **Volumen persistente**: `postgres_data:/var/lib/postgresql/data` para que los datos sobrevivan a reinicios de contenedores.
- **Healthcheck robusto**:
  ```yaml
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-sismo} -d ${POSTGRES_DB:-sismos}"]
    interval: 5s
    timeout: 5s
    retries: 10
    start_period: 10s
  ```

---

## 3. Configuración de Apache Kafka 3.8 en modo KRaft (`kafka`)

El enunciado prohíbe o desaconseja el despliegue obsoleto con ZooKeeper. Usamos **Apache Kafka oficial con KRaft** (Kafka Raft Metadata Mode):

- **Imagen**: `apache/kafka:3.8.0`
- **Variables de entorno KRaft**:
  - `KAFKA_NODE_ID: 1`
  - `KAFKA_PROCESS_ROLES: broker,controller`
  - `KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093`
  - `KAFKA_LISTENERS: PLAINTEXT://:9092,CONTROLLER://:9093`
  - `KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092`
  - `KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT`
  - `KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER`
  - `KAFKA_LOG_DIRS: /tmp/kraft-combined-logs`
  - `KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1`
  - `KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 1`
  - `KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: 1`
  - `KAFKA_LOG_RETENTION_HOURS: 48` (retención acotada según enunciado)
- **Healthcheck de Kafka**:
  ```yaml
  healthcheck:
    test: ["CMD-SHELL", "/opt/kafka/bin/kafka-cluster.sh cluster-id --bootstrap-server localhost:9092 || exit 1"]
    interval: 10s
    timeout: 5s
    retries: 10
    start_period: 15s
  ```

---

## 4. Imagen Python Compartida (`Dockerfile.python`)

Para evitar duplicar código y descargas de paquetes, se utiliza un único `Dockerfile.python` multi-propósito basado en `python:3.12-slim`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Instalar dependencias del sistema mínimas necesarias para compilación C de shapely/psycopg si aplica
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libgeos-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY sql/ ./sql/
COPY frontend/public/datos/paises.geojson ./frontend/public/datos/paises.geojson

ENV PYTHONUNBUFFERED=1
```

Cada servicio en Docker Compose reutiliza esta misma imagen cambiando el comando de inicio (`command`):
- **producer**: `command: ["python", "-m", "backend.producer.producer"]`
- **consumer**: `command: ["python", "-m", "backend.consumer.consumer"]`
- **api**: `command: ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]`

---

## 5. Gestión de Secretos y Variables de Entorno

- **`.env.example`**: Plantilla subida a Git con valores predeterminados seguros para desarrollo local (nunca contiene contraseñas de producción).
- **`.env`**: Archivo local del alumno (añadido en `.gitignore`).
- Variables requeridas:
  ```env
  POSTGRES_DB=sismos
  POSTGRES_USER=sismo
  POSTGRES_PASSWORD=sismo_secreto
  POSTGRES_HOST=postgres
  POSTGRES_PORT=5432

  KAFKA_BOOTSTRAP_SERVERS=kafka:9092
  KAFKA_TOPIC=terremotos
  KAFKA_TOPIC_REPLAY=terremotos-replay
  KAFKA_CONSUMER_GROUP=observatorio-consumidor

  USGS_FEED_URL=https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson
  USGS_POLL_INTERVAL_SECONDS=60

  API_HOST=0.0.0.0
  API_PORT=8000
  CORS_ORIGINS=http://localhost:4200,https://*.netlify.app
  ```

---

## 6. Procedimiento de Arranque y Validación

1. Construir e iniciar en segundo plano:
   ```bash
   docker compose up --build -d
   ```
2. Verificar el estado de salud de todos los servicios:
   ```bash
   docker compose ps
   ```
   *Todos los servicios deben mostrar `healthy` o `running`.*
3. Inspeccionar logs de un servicio concreto:
   ```bash
   docker compose logs -f consumer
   docker compose logs -f producer
   docker compose logs -f api
   ```
4. Apagar y limpiar volúmenes (si se requiere reiniciar desde cero):
   ```bash
   docker compose down -v
   ```
