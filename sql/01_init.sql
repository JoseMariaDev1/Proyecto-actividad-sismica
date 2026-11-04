-- ============================================================================
-- PROYECTO: Observatorio de Actividad Sísmica (Big Data / Streaming)
-- FICHERO: 01_init.sql
-- MOTOR: PostgreSQL 16
-- AUTOR: db-architect
-- DESCRIPCIÓN: DDL de inicialización de la capa de almacenamiento relacional.
--
-- CUMPLE REQUISITOS:
-- 1. Catálogo normalizado de países (Natural Earth ADM0_A3).
-- 2. Trazabilidad raw original GeoJSON para auditoría y reproducibilidad.
-- 3. Tabla principal 'eventos' enriquecida, validada y tipada.
-- 4. Soporte para nulos y magnitudes/profundidades negativas (sin pérdida).
-- 5. Historial inmutable de versiones para USGS (FAQ 12).
-- 6. Cola de cuarentena para registros corruptos o fallos de validación.
-- 7. Persistencia de estado del productor/ingesta.
-- 8. Índices B-Tree optimizados para consultas temporales y analíticas.
-- 9. Procedimiento atómico e idempotente de inserción/actualización.
-- 10. Vistas analíticas y de integración con el contrato de la API.
-- ============================================================================

-- Configuración de zona horaria por defecto en UTC
SET timezone = 'UTC';

-- ----------------------------------------------------------------------------
-- 1. TABLA: paises
-- Catálogo geográfico de 177 países de Natural Earth.
-- Grano: 1 fila por país administrativo soberano.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS paises (
    code        VARCHAR(3) PRIMARY KEY,               -- Código ADM0_A3 de 3 letras (ej. 'ESP', 'USA', 'CHL')
    name_es     VARCHAR(150) NOT NULL,                -- Nombre común en español (ej. 'España', 'Chile')
    admin       VARCHAR(150) NOT NULL,                -- Nombre administrativo oficial (ej. 'Spain')
    continent   VARCHAR(100),                         -- Continente (ej. 'Europe', 'South America')
    subregion   VARCHAR(100),                         -- Subregión geográfica (ej. 'Southern Europe')
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()    -- Timestamp de creación
);

COMMENT ON TABLE paises IS 'Catálogo de países derivado de Natural Earth GeoJSON 110m (177 entidades)';
COMMENT ON COLUMN paises.code IS 'Código ADM0_A3 (clave primaria de 3 caracteres alfabéticos)';
COMMENT ON COLUMN paises.name_es IS 'Nombre oficial o comúnmente aceptado en lengua española';

-- Índices en países para consultas analíticas y agrupaciones regionales
CREATE INDEX IF NOT EXISTS idx_paises_continent ON paises (continent);
CREATE INDEX IF NOT EXISTS idx_paises_subregion ON paises (subregion);


-- ----------------------------------------------------------------------------
-- 2. TABLA: eventos_raw
-- Almacena el GeoJSON original del evento tal como llega de USGS o Kafka.
-- Garantiza trazabilidad completa, reproducibilidad y auditoría forense.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eventos_raw (
    id          BIGSERIAL PRIMARY KEY,                -- Identificador secuencial de ingesta
    id_evento   VARCHAR(100) NOT NULL,                -- Identificador original USGS (ej. 'us7000m8v4')
    source      VARCHAR(50) NOT NULL DEFAULT 'usgs',  -- Fuente del dato ('usgs', 'synthetic_test', etc.)
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),   -- Hora UTC de recepción en el sistema
    mode        VARCHAR(20) NOT NULL DEFAULT 'live',  -- Modo de ejecución ('live' o 'replay')
    raw_json    JSONB NOT NULL,                       -- Payload JSON íntegro original
    CONSTRAINT chk_raw_mode CHECK (mode IN ('live', 'replay', 'synthetic'))
);

COMMENT ON TABLE eventos_raw IS 'Almacén de auditoría con la carga útil GeoJSON original sin transformaciones';
COMMENT ON COLUMN eventos_raw.raw_json IS 'Documento JSONB con la Feature original recibida';

-- Índices para búsqueda de auditoría por evento y ventana temporal de ingesta
CREATE INDEX IF NOT EXISTS idx_eventos_raw_id_evento ON eventos_raw (id_evento, ingested_at DESC);
CREATE INDEX IF NOT EXISTS idx_eventos_raw_ingested_at ON eventos_raw (ingested_at DESC);


-- ----------------------------------------------------------------------------
-- 3. TABLA: eventos (Estado actual / Hecho del terremoto)
-- Almacena la versión más reciente, limpia y enriquecida de cada sismo.
-- Grano: 1 fila por evento sismológico único (id USGS).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eventos (
    id            VARCHAR(100) PRIMARY KEY,              -- ID único oficial de USGS (ej. 'nc73894721')
    time          TIMESTAMPTZ NOT NULL,                  -- Momento UTC exacto de la ocurrencia del sismo
    updated       TIMESTAMPTZ NOT NULL,                  -- Timestamp UTC de la última revisión emitida por USGS
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),    -- Momento UTC en que nuestro sistema procesó el evento
    mag           DOUBLE PRECISION,                      -- Magnitud. Admite NULL (no calculada) y negativas (microterremotos)
    mag_type      VARCHAR(50),                           -- Método de cálculo (ej. 'ml', 'md', 'mw', 'mb')
    place         TEXT,                                  -- Descripción textual del epicentro
    longitude     DOUBLE PRECISION NOT NULL,             -- Longitud en grados decimales WGS84 [-180, 180]
    latitude      DOUBLE PRECISION NOT NULL,             -- Latitud en grados decimales WGS84 [-90, 90]
    depth         DOUBLE PRECISION,                      -- Profundidad focal en km. Negativa = sobre el nivel del mar
    country_code  VARCHAR(3) REFERENCES paises(code)     -- FK a país. NULL si es sismo marítimo o en aguas internacionales
                  ON DELETE SET NULL,
    status        VARCHAR(50) DEFAULT 'automatic',       -- Estado de revisión USGS ('automatic', 'reviewed')
    event_type    VARCHAR(50) DEFAULT 'earthquake',      -- Tipo de evento ('earthquake', 'quarry blast', etc.)
    tsunami       INTEGER NOT NULL DEFAULT 0,            -- Indicador de alerta de tsunami (0 = no, 1 = sí)
    sig           INTEGER,                               -- Índice de significancia sísmica [0, 1000]
    mode          VARCHAR(20) NOT NULL DEFAULT 'live',   -- Modo operativo ('live' en tiempo real o 'replay' histórico)

    -- Restricciones de integridad de dominio (Validation / Quality)
    CONSTRAINT chk_latitude  CHECK (latitude BETWEEN -90.0 AND 90.0),
    CONSTRAINT chk_longitude CHECK (longitude BETWEEN -180.0 AND 180.0),
    CONSTRAINT chk_mode      CHECK (mode IN ('live', 'replay', 'synthetic')),
    CONSTRAINT chk_tsunami   CHECK (tsunami IN (0, 1))
);

COMMENT ON TABLE eventos IS 'Tabla de estado actual consultable de eventos sísmicos limpios y geolocalizados';
COMMENT ON COLUMN eventos.mag IS 'Magnitud sísmica. Puede ser nula o negativa (microseísmos válidos)';
COMMENT ON COLUMN eventos.depth IS 'Profundidad focal en kilómetros. Puede ser negativa en cimas de montañas/volcanes';
COMMENT ON COLUMN eventos.country_code IS 'Código de país asignado espacialmente. NULO si ocurrió en mar abierto';

-- ----------------------------------------------------------------------------
-- ÍNDICES ESTRATÉGICOS PARA OPTIMIZACIÓN DE CONSULTAS
-- ----------------------------------------------------------------------------

-- 1. Consulta por rango temporal (GET /api/eventos?start=...&end=...): O(log N)
CREATE INDEX IF NOT EXISTS idx_eventos_time ON eventos (time DESC);

-- 2. Filtrado por país (GET /api/eventos?country_id=...):
CREATE INDEX IF NOT EXISTS idx_eventos_country_code ON eventos (country_code);

-- 3. Filtrado por magnitud mínima (GET /api/eventos?min_mag=...):
-- Índice parcial que ignora nulos (los nulos se consultan y contabilizan por separado según enunciado)
CREATE INDEX IF NOT EXISTS idx_eventos_mag ON eventos (mag) WHERE mag IS NOT NULL;

-- 4. Índice compuesto temporal + magnitud (clave para mapa dinámico y filtros concurrentes):
CREATE INDEX IF NOT EXISTS idx_eventos_time_mag ON eventos (time DESC, mag);

-- 5. Índice compuesto temporal + país (para estadísticas de ventanas de 1h por país):
CREATE INDEX IF NOT EXISTS idx_eventos_time_country ON eventos (time DESC, country_code);

-- 6. Índice de control de modo (aísla datos de simulación 'replay' de producción 'live'):
CREATE INDEX IF NOT EXISTS idx_eventos_mode ON eventos (mode);

-- 7. Índice de control de actualización USGS:
CREATE INDEX IF NOT EXISTS idx_eventos_updated ON eventos (updated DESC);


-- ----------------------------------------------------------------------------
-- 4. TABLA: eventos_versiones
-- Registro histórico inmutable de revisiones recibidas desde USGS.
-- Grano: 1 fila por cada par único (id_evento, updated).
-- Cumple regla de evaluación FAQ-12: múltiples revisiones conservan su histórico.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eventos_versiones (
    id            BIGSERIAL PRIMARY KEY,                 -- Secuencial interno de versión
    id_evento     VARCHAR(100) NOT NULL,                 -- Identificador del sismo
    updated       TIMESTAMPTZ NOT NULL,                  -- Timestamp USGS de esta revisión específica
    version_num   INTEGER NOT NULL DEFAULT 1,            -- Número ordinal de versión observada (1, 2, 3...)
    snapshot_json JSONB NOT NULL,                        -- Instantánea completa con magnitud, posición y campos
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),    -- Timestamp local de registro de la versión
    CONSTRAINT uq_eventos_versiones UNIQUE (id_evento, updated)
);

COMMENT ON TABLE eventos_versiones IS 'Historial de revisiones de sismos. Cada versión conserva un snapshot inmutable';

-- Índice para recuperación rápida del árbol de versiones de un evento
CREATE INDEX IF NOT EXISTS idx_versiones_evento ON eventos_versiones (id_evento, version_num DESC);


-- ----------------------------------------------------------------------------
-- 5. TABLA: eventos_cuarentena
-- Almacén de aislamiento para mensajes corruptos, coordenadas imposibles o JSONs inválidos.
-- Permite que el consumidor continúe su flujo sin caerse ni perder información.
-- Grano: 1 fila por cada payload anómalo rechazado con su diagnóstico técnico.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eventos_cuarentena (
    id           SERIAL PRIMARY KEY,                    -- Identificador del incidente
    event_id     VARCHAR(100),                          -- ID si se pudo extraer, o NULL si el payload estaba truncado
    reason       TEXT NOT NULL,                         -- Diagnóstico del rechazo (ej. 'Latitud fuera de rango: 120.4')
    raw_payload  TEXT NOT NULL,                         -- Mensaje original en crudo (tipo TEXT para soportar JSON roto)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()     -- Momento del descarte
);

COMMENT ON TABLE eventos_cuarentena IS 'Buzón de aislamiento de eventos inválidos o corruptos con su motivo de descarte';

CREATE INDEX IF NOT EXISTS idx_cuarentena_event_id ON eventos_cuarentena (event_id);
CREATE INDEX IF NOT EXISTS idx_cuarentena_created_at ON eventos_cuarentena (created_at DESC);


-- ----------------------------------------------------------------------------
-- 6. TABLA: estado_productor
-- Almacenamiento clave-valor JSONB para la persistencia del extractor/consumidor.
-- Garantiza tolerancia a caídas y reinicio sin reprocesamiento masivo.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS estado_productor (
    key         VARCHAR(100) PRIMARY KEY,              -- Clave identificadora (ej. 'extractor_live_status')
    value       JSONB NOT NULL,                        -- Contenido estructurado de estado (timestamps, contadores)
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()     -- Timestamp de actualización
);

COMMENT ON TABLE estado_productor IS 'Almacén persistente de estado y salud para productores y consumidores';

-- Inserción de estado inicial por defecto
INSERT INTO estado_productor (key, value, updated_at)
VALUES (
    'extractor_usgs_live',
    '{"last_successful_poll": null, "last_ingested_event_time": null, "status": "initialized", "events_processed_count": 0, "error_count": 0}'::jsonb,
    NOW()
)
ON CONFLICT (key) DO NOTHING;


-- ----------------------------------------------------------------------------
-- 7. PROCEDIMIENTOS Y FUNCIONES AUXILIARES
-- Implementación del patrón de procesamiento idempotente y versionado atómico.
-- ----------------------------------------------------------------------------

-- Función para actualizar el estado del extractor
CREATE OR REPLACE FUNCTION fn_actualizar_estado(p_key VARCHAR, p_val JSONB)
RETURNS VOID AS $$
BEGIN
    INSERT INTO estado_productor (key, value, updated_at)
    VALUES (p_key, p_val, NOW())
    ON CONFLICT (key) DO UPDATE
    SET value = EXCLUDED.value,
        updated_at = NOW();
END;
$$ LANGUAGE plpgsql;

-- Función atómica para inserción idempotente con control estricto de revisiones (FAQ 12)
CREATE OR REPLACE FUNCTION fn_ingestar_evento(
    p_id           VARCHAR,
    p_time         TIMESTAMPTZ,
    p_updated      TIMESTAMPTZ,
    p_mag          DOUBLE PRECISION,
    p_mag_type     VARCHAR,
    p_place        TEXT,
    p_longitude    DOUBLE PRECISION,
    p_latitude     DOUBLE PRECISION,
    p_depth        DOUBLE PRECISION,
    p_country_code VARCHAR,
    p_status       VARCHAR,
    p_event_type   VARCHAR,
    p_tsunami      INTEGER,
    p_sig          INTEGER,
    p_mode         VARCHAR,
    p_snapshot     JSONB
)
RETURNS VARCHAR AS $$
DECLARE
    v_actual_updated TIMESTAMPTZ;
    v_next_version   INTEGER;
    v_resultado      VARCHAR;
BEGIN
    -- 1. Comprobar si el evento ya existe en la tabla principal
    SELECT updated INTO v_actual_updated
    FROM eventos
    WHERE id = p_id;

    IF NOT FOUND THEN
        -- Caso A: Evento nuevo -> Inserción directa
        INSERT INTO eventos (
            id, time, updated, ingested_at, mag, mag_type, place,
            longitude, latitude, depth, country_code, status,
            event_type, tsunami, sig, mode
        ) VALUES (
            p_id, p_time, p_updated, NOW(), p_mag, p_mag_type, p_place,
            p_longitude, p_latitude, p_depth, p_country_code, p_status,
            p_event_type, p_tsunami, p_sig, p_mode
        );

        -- Registrar primera versión
        INSERT INTO eventos_versiones (id_evento, updated, version_num, snapshot_json, recorded_at)
        VALUES (p_id, p_updated, 1, p_snapshot, NOW())
        ON CONFLICT (id_evento, updated) DO NOTHING;

        v_resultado := 'INSERTED_NEW';

    ELSIF p_updated > v_actual_updated THEN
        -- Caso B: Revisión más reciente recibida -> Actualizar tabla principal
        UPDATE eventos SET
            time         = p_time,
            updated      = p_updated,
            ingested_at  = NOW(),
            mag          = p_mag,
            mag_type     = p_mag_type,
            place        = p_place,
            longitude    = p_longitude,
            latitude     = p_latitude,
            depth        = p_depth,
            country_code = p_country_code,
            status       = p_status,
            event_type   = p_event_type,
            tsunami      = p_tsunami,
            sig          = p_sig,
            mode         = p_mode
        WHERE id = p_id;

        -- Calcular siguiente número de versión
        SELECT COALESCE(MAX(version_num), 1) + 1 INTO v_next_version
        FROM eventos_versiones
        WHERE id_evento = p_id;

        -- Registrar nueva versión histórica
        INSERT INTO eventos_versiones (id_evento, updated, version_num, snapshot_json, recorded_at)
        VALUES (p_id, p_updated, v_next_version, p_snapshot, NOW())
        ON CONFLICT (id_evento, updated) DO NOTHING;

        v_resultado := 'UPDATED_REVISION';

    ELSE
        -- Caso C: Mensaje duplicado o revisión anterior retrasada -> No sobreescribir (Idempotencia)
        -- Si la versión no estaba registrada por alguna razón, guardarla en histórico
        INSERT INTO eventos_versiones (id_evento, updated, version_num, snapshot_json, recorded_at)
        SELECT p_id, p_updated, COALESCE(MAX(version_num), 0) + 1, p_snapshot, NOW()
        FROM eventos_versiones
        WHERE id_evento = p_id
        ON CONFLICT (id_evento, updated) DO NOTHING;

        v_resultado := 'IGNORED_OUTDATED_OR_DUPLICATE';
    END IF;

    RETURN v_resultado;
END;
$$ LANGUAGE plpgsql;


-- ----------------------------------------------------------------------------
-- 8. VISTAS ANALÍTICAS Y CONTRATO DE API
-- ----------------------------------------------------------------------------

-- Vista 1: Adaptador para el endpoint GET /api/eventos (Contrato GeoJSON)
-- Formatea los eventos exactamente como los requiere el mapa y frontend de Angular.
CREATE OR REPLACE VIEW v_eventos_api AS
SELECT
    e.id,
    e.time,
    e.updated,
    e.mag,
    e.mag_type,
    e.place,
    e.longitude,
    e.latitude,
    e.depth,
    e.country_code AS country_id,
    COALESCE(p.name_es, 'Sin país asignado') AS country_name,
    p.continent,
    p.subregion,
    e.status,
    e.tsunami,
    e.sig,
    e.mode,
    -- Representación en milisegundos Unix epoch para compatibilidad estricta con CONTRATO-API.md
    (EXTRACT(EPOCH FROM e.time) * 1000)::BIGINT AS time_epoch_ms,
    (EXTRACT(EPOCH FROM e.updated) * 1000)::BIGINT AS updated_epoch_ms
FROM eventos e
LEFT JOIN paises p ON e.country_code = p.code;

COMMENT ON VIEW v_eventos_api IS 'Vista adaptada al Contrato Mínimo de la API (unión con nombres de países en español y epoch en ms)';


-- Vista 2: Agrupación en ventanas fijas de 1 hora UTC (Requisito 8 y FAQ 22)
-- Agrupa por hora de ocurrencia UTC (no de ingesta)
CREATE OR REPLACE VIEW v_estadisticas_horarias AS
SELECT
    DATE_TRUNC('hour', time) AS ventana_hora_utc,
    COALESCE(country_code, 'SIN_PAIS') AS country_id,
    mode,
    COUNT(*) AS total_eventos,
    ROUND(AVG(mag)::NUMERIC, 2) AS mag_promedio,
    MAX(mag) AS mag_maxima,
    MIN(mag) AS mag_minima,
    COUNT(CASE WHEN mag IS NULL THEN 1 END) AS count_mag_nula,
    COUNT(CASE WHEN depth IS NULL THEN 1 END) AS count_depth_nula,
    COUNT(CASE WHEN tsunami = 1 THEN 1 END) AS count_alertas_tsunami
FROM eventos
GROUP BY DATE_TRUNC('hour', time), COALESCE(country_code, 'SIN_PAIS'), mode;

COMMENT ON VIEW v_estadisticas_horarias IS 'Métricas agregadas en ventanas de 1 hora UTC por país y modo';


-- Vista 3: Monitor de Calidad de Datos (Rúbrica: Calidad y Transformación)
-- Proporciona porcentajes de completitud en tiempo real para memoria técnica / notebook
CREATE OR REPLACE VIEW v_calidad_datos AS
SELECT
    COUNT(*) AS total_eventos_actuales,
    COUNT(CASE WHEN mag IS NOT NULL THEN 1 END) AS count_mag_presente,
    ROUND((COUNT(CASE WHEN mag IS NOT NULL THEN 1 END)::NUMERIC / NULLIF(COUNT(*), 0) * 100), 2) AS pct_completitud_mag,
    COUNT(CASE WHEN mag IS NULL THEN 1 END) AS count_mag_nula,
    COUNT(CASE WHEN depth IS NOT NULL THEN 1 END) AS count_depth_presente,
    ROUND((COUNT(CASE WHEN depth IS NOT NULL THEN 1 END)::NUMERIC / NULLIF(COUNT(*), 0) * 100), 2) AS pct_completitud_depth,
    COUNT(CASE WHEN country_code IS NOT NULL THEN 1 END) AS count_con_pais,
    COUNT(CASE WHEN country_code IS NULL THEN 1 END) AS count_maritimos_sin_pais,
    (SELECT COUNT(*) FROM eventos_versiones) AS total_versiones_registradas,
    (SELECT COUNT(*) FROM eventos_cuarentena) AS total_descartes_cuarentena
FROM eventos;

COMMENT ON VIEW v_calidad_datos IS 'Métricas globales de completitud y dimensiones de calidad para el informe técnico';
