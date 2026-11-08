"""
Módulo principal del Servicio API REST para el Observatorio de Actividad Sísmica.

Implementa los endpoints especificados en CONTRATO-API.md y la rúbrica del proyecto:
1. GET /api/salud: Verificación de estado de la API, conectividad PostgreSQL y última ingesta.
2. GET /api/eventos: GeoJSON FeatureCollection estándar con filtros espaciotemporales.
3. GET /api/estadisticas: Agregaciones analíticas (magnitud, profundidad, ventanas 1h UTC, top países).
4. GET /api/paises: Catálogo de países de Natural Earth para filtros del frontend.

Adicionalmente incluye:
- Configuración CORS para Netlify, localhost y ngrok.
- Gestión de ciclo de vida (Lifespan) con AsyncConnectionPool de psycopg 3.
- Documentación OpenAPI / Swagger (/docs) y ReDoc (/redoc).
"""

from __future__ import annotations

import asyncio
import logging
import math
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from backend.common.config import Settings, get_settings

# Ajuste necesario en Windows para permitir polling asíncrono con psycopg
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

# Configuración de logging estructurado en español
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sismos.api")


# ==============================================================================
# Modelos Pydantic v2 (Esquemas de Entrada y Salida)
# ==============================================================================

class SaludResponse(BaseModel):
    """Respuesta para el endpoint de monitorización de salud /api/salud."""
    estado: str = Field(..., description="Estado del servicio: 'ok' o 'error'")
    version: str = Field("1.0.0", description="Versión semántica del API")
    bd_conectada: bool = Field(..., description="Indica si hay conectividad activa con PostgreSQL")
    timestamp: str = Field(..., description="Marca temporal UTC actual en formato ISO 8601")
    ultima_ingesta: Optional[str] = Field(None, description="Timestamp UTC del último evento registrado en BD")
    modo_default: str = Field("live", description="Modo operativo por defecto")


class EventProperties(BaseModel):
    """Propiedades de un evento sísmico en el GeoJSON Feature."""
    id: str = Field(..., description="Identificador único del sismo emitido por USGS")
    time: int = Field(..., description="Marca de tiempo del seísmo en milisegundos Unix epoch UTC")
    updated: int = Field(..., description="Marca de tiempo de última revisión USGS en ms Unix epoch UTC")
    mag: Optional[float] = Field(None, description="Magnitud sísmica (puede ser nula o negativa)")
    magType: Optional[str] = Field(None, description="Tipo de cálculo de magnitud sísmica (ej. 'mw', 'ml')")
    place: str = Field(..., description="Descripción geográfica o topológica del epicentro")
    country_id: Optional[str] = Field(None, description="Código ISO/ADM0_A3 de 3 letras del país")
    country_name: Optional[str] = Field(None, description="Nombre común oficial del país en español")
    status: Optional[str] = Field("automatic", description="Estado de revisión del seísmo ('automatic' o 'reviewed')")
    mode: Optional[str] = Field("live", description="Modo de ejecución ('live' o 'replay')")
    tsunami: Optional[int] = Field(0, description="Indicador de alerta de tsunami (0 o 1)")
    sig: Optional[int] = Field(None, description="Índice de significancia sísmica [0, 1000]")


class GeoJSONPoint(BaseModel):
    """Geometría GeoJSON de tipo Point conforme al RFC 7946."""
    type: str = "Point"
    coordinates: List[Optional[float]] = Field(
        ...,
        description="Coordenadas en orden estricto [longitud, latitud, profundidad_km]",
        min_length=2,
        max_length=3,
    )


class GeoJSONFeature(BaseModel):
    """Elemento Feature individual dentro de la FeatureCollection."""
    type: str = "Feature"
    id: str = Field(..., description="Identificador del evento sismológico")
    geometry: GeoJSONPoint
    properties: EventProperties


class GeoJSONMetadata(BaseModel):
    """Metadatos de la colección conforme a CONTRATO-API.md."""
    total: int = Field(..., description="Total de eventos en la BD que coinciden con los filtros")
    count: int = Field(..., description="Número de eventos devueltos en este lote o página")
    limite: int = Field(..., description="Límite máximo de eventos solicitados")
    offset: int = Field(..., description="Desplazamiento para paginación")
    generated: int = Field(..., description="Timestamp de generación de la respuesta en ms Unix epoch UTC")
    last_ingestion: Optional[int] = Field(None, description="Timestamp de última ingesta a BD en ms Unix epoch UTC")
    mode: str = Field("live", description="Modo operativo consultado")
    truncated: bool = Field(..., description="Indica si existen eventos adicionales que no cupieron en el límite")


class GeoJSONFeatureCollection(BaseModel):
    """GeoJSON FeatureCollection estándar conforme al contrato de API."""
    type: str = "FeatureCollection"
    metadata: GeoJSONMetadata
    features: List[GeoJSONFeature]


class PaisItem(BaseModel):
    """Entidad de país georreferenciado."""
    code: str = Field(..., description="Código ADM0_A3 de 3 letras (ej. 'ESP')")
    name_es: str = Field(..., description="Nombre común oficial en español")
    admin: str = Field(..., description="Nombre administrativo en inglés")
    continent: Optional[str] = Field(None, description="Continente")
    subregion: Optional[str] = Field(None, description="Subregión geográfica")


class EventoMaximo(BaseModel):
    """Detalle del terremoto de mayor magnitud en el periodo."""
    id: str
    mag: float
    place: str
    time: str
    time_epoch_ms: int
    country_id: Optional[str] = None
    country_name: Optional[str] = None


class DistribucionMagnitud(BaseModel):
    """Distribución de sismos por rangos de magnitud."""
    menor_3: int = Field(..., description="Magnitud inferior a 3.0 (< 3)")
    de_3_a_4_5: int = Field(..., description="Magnitud entre 3.0 y 4.5 [3.0, 4.5)")
    de_4_5_a_6: int = Field(..., description="Magnitud entre 4.5 y 6.0 [4.5, 6.0)")
    mayor_igual_6: int = Field(..., description="Magnitud igual o superior a 6.0 (>= 6.0)")
    sin_magnitud: int = Field(..., description="Sismos con magnitud no determinada o nula")


class DistribucionProfundidad(BaseModel):
    """Distribución de sismos por rangos de profundidad focal."""
    someros_0_70km: int = Field(..., description="Sismos someros (< 70 km de profundidad)")
    intermedios_70_300km: int = Field(..., description="Sismos intermedios [70 km, 300 km)")
    profundos_mas_300km: int = Field(..., description="Sismos profundos (>= 300 km)")
    sin_profundidad: int = Field(..., description="Sismos sin profundidad determinada o nula")


class VentanaHoraria(BaseModel):
    """Agrupación analítica en ventana fija de 1 hora UTC."""
    hora_utc: str = Field(..., description="Momento de inicio de la hora en formato ISO 8601 UTC")
    recuento: int = Field(..., description="Total de sismos ocurridos en la hora")
    mag_promedio: Optional[float] = Field(None, description="Magnitud media en la ventana")
    mag_maxima: Optional[float] = Field(None, description="Magnitud máxima registrada en la ventana")


class TopPais(BaseModel):
    """País con mayor número de seísmos registrados."""
    pais_codigo: str = Field(..., description="Código ADM0_A3 del país")
    pais_nombre: str = Field(..., description="Nombre del país en español")
    recuento: int = Field(..., description="Recuento de terremotos registrados")


class EstadisticasResponse(BaseModel):
    """Respuesta completa del endpoint de analítica /api/estadisticas."""
    total_eventos: int
    mag_promedio: Optional[float] = None
    max_magnitud: Optional[EventoMaximo] = None
    distribucion_magnitud: DistribucionMagnitud
    distribucion_profundidad: DistribucionProfundidad
    ventanas_horarias: List[VentanaHoraria]
    top_paises: List[TopPais]
    comparativa_historico: Dict[str, Any]
    metadata: Dict[str, Any]


# ==============================================================================
# Funciones Utilitarias de Parseo y Formato
# ==============================================================================

def parse_datetime(val: Optional[Union[str, datetime, int, float]]) -> Optional[datetime]:
    """
    Parsea de forma robusta marcas temporales en ISO 8601, cadenas de fecha o epochs.
    Asegura que el objeto retornado tenga siempre zona horaria UTC explícita.
    """
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if isinstance(val, (int, float)):
        # Si el valor supera 1e11 asumimos milisegundos Unix epoch
        if val > 1e11:
            return datetime.fromtimestamp(val / 1000.0, tz=timezone.utc)
        return datetime.fromtimestamp(val, tz=timezone.utc)
    if isinstance(val, str):
        v = val.strip()
        if not v:
            return None
        # Intentar parsear como timestamp numérico en string
        try:
            num = float(v)
            return parse_datetime(num)
        except ValueError:
            pass
        # Intentar parsear como ISO 8601 estándar
        try:
            cleaned = v.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Formato de fecha inválido '{val}'. Se requiere formato ISO 8601 UTC (ej. '2026-11-08T00:00:00Z') o milisegundos Unix epoch.",
            )
    return None


def to_epoch_ms(dt: Optional[datetime]) -> Optional[int]:
    """Convierte un objeto datetime UTC a milisegundos Unix epoch."""
    if dt is None:
        return None
    return int(round(dt.timestamp() * 1000))


# ==============================================================================
# Ciclo de Vida de la Aplicación (Lifespan)
# ==============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Gestiona el ciclo de vida de la aplicación FastAPI.
    Inicializa el pool de conexiones asíncronas hacia PostgreSQL y lo libera al detenerse.
    """
    settings: Settings = get_settings()
    logger.info("Inicializando servicio API REST del Observatorio de Actividad Sísmica...")
    logger.info(f"Conectando a PostgreSQL en {settings.postgres.host}:{settings.postgres.port}/{settings.postgres.database}...")

    pool: Optional[AsyncConnectionPool] = None
    try:
        pool = AsyncConnectionPool(
            conninfo=settings.postgres.dsn,
            min_size=2,
            max_size=20,
            max_idle=300,
            timeout=10.0,
            open=False,
            kwargs={"row_factory": dict_row},
        )
        await pool.open(wait=False)
        app.state.pool = pool
        logger.info("Pool de conexiones asíncronas a PostgreSQL configurado satisfactoriamente.")
    except Exception as exc:
        logger.warning(
            f"No fue posible conectar inmediatamente a PostgreSQL: {exc}. "
            "El API iniciará en modo resiliente."
        )
        app.state.pool = pool

    try:
        yield
    finally:
        logger.info("Deteniendo servicio API REST...")
        active_pool: Optional[AsyncConnectionPool] = getattr(app.state, "pool", None)
        if active_pool is not None:
            try:
                await active_pool.close()
                logger.info("Pool de conexiones a PostgreSQL cerrado correctamente.")
            except Exception as exc:
                logger.error(f"Error al cerrar el pool de PostgreSQL: {exc}")


# ==============================================================================
# Instanciación de la Aplicación FastAPI
# ==============================================================================

app = FastAPI(
    title="Observatorio de Actividad Sísmica - API REST",
    description=(
        "Servicio API REST para la consulta en tiempo real e histórica de actividad sismológica global. "
        "Cumple estrictamente con el contrato GeoJSON RFC 7946, CONTRATO-API.md, "
        "y proporciona endpoints analíticos y de catálogo para clientes web Angular y túneles ngrok."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Configuración de orígenes CORS
_settings = get_settings()
_cors_origins = [orig for orig in _settings.api.cors_origins if "*" not in orig]
if not _cors_origins:
    _cors_origins = ["http://localhost:4200", "http://127.0.0.1:4200"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"^https://([a-zA-Z0-9-]+\.)*netlify\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "ngrok-skip-browser-warning"],
    expose_headers=["*", "ngrok-skip-browser-warning"],
)


@app.middleware("http")
async def add_ngrok_headers_middleware(request: Request, call_next):
    """
    Middleware para admitir y propagar cabeceras especiales como ngrok-skip-browser-warning
    evitando pantallas intermedias de túneles ngrok en entornos remotos.
    """
    response = await call_next(request)
    response.headers["ngrok-skip-browser-warning"] = "any"
    return response


# ==============================================================================
# Inyección de Dependencias: Base de Datos
# ==============================================================================

async def get_db(request: Request) -> AsyncGenerator[psycopg.AsyncConnection, None]:
    """
    Dependencia de FastAPI que adquiere una conexión del pool asíncrono
    y garantiza su devolución ordenada al finalizar la petición HTTP.
    """
    pool: Optional[AsyncConnectionPool] = getattr(request.app.state, "pool", None)
    if pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servicio de base de datos PostgreSQL no se encuentra inicializado.",
        )
    try:
        async with pool.connection(timeout=5.0) as conn:
            yield conn
    except (psycopg.OperationalError, psycopg.DatabaseError, TimeoutError, Exception) as exc:
        logger.error(f"Error operacional al obtener conexión de base de datos: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Fallo de comunicación con la base de datos relacional PostgreSQL.",
        )


# ==============================================================================
# Endpoint 1: GET /api/salud
# ==============================================================================

@app.get(
    "/api/salud",
    response_model=SaludResponse,
    summary="Verificación de salud y conectividad",
    description="Comprueba la operatividad de la API, ejecuta un 'SELECT 1' en PostgreSQL y reporta la última ingesta.",
    tags=["Monitorización"],
)
async def get_salud(request: Request) -> SaludResponse:
    now_utc = datetime.now(timezone.utc).isoformat()
    pool: Optional[AsyncConnectionPool] = getattr(request.app.state, "pool", None)

    if pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "estado": "error",
                "version": "1.0.0",
                "bd_conectada": False,
                "timestamp": now_utc,
                "mensaje": "Pool de conexiones no disponible.",
            },
        )

    try:
        async with pool.connection(timeout=4.0) as conn:
            async with conn.cursor() as cur:
                # Comprobación de salud básica
                await cur.execute("SELECT 1;")
                
                # Consultar última fecha de ingesta conocida
                ultima_ingesta_iso: Optional[str] = None
                try:
                    await cur.execute(
                        "SELECT MAX(ingested_at) AS max_ingested FROM eventos;"
                    )
                    row = await cur.fetchone()
                    if row and row.get("max_ingested"):
                        dt = row["max_ingested"]
                        if isinstance(dt, datetime):
                            ultima_ingesta_iso = dt.isoformat()
                except Exception:
                    # Si la tabla aún no existe o está vacía, continuar limpiamente
                    pass

                return SaludResponse(
                    estado="ok",
                    version="1.0.0",
                    bd_conectada=True,
                    timestamp=now_utc,
                    ultima_ingesta=ultima_ingesta_iso,
                    modo_default="live",
                )
    except Exception as exc:
        logger.error(f"Fallo de verificación de salud contra la base de datos: {exc}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "estado": "error",
                "version": "1.0.0",
                "bd_conectada": False,
                "timestamp": now_utc,
                "mensaje": f"No se pudo verificar PostgreSQL: {str(exc)}",
            },
        )


# ==============================================================================
# Endpoint 2: GET /api/eventos
# ==============================================================================

@app.get(
    "/api/eventos",
    response_model=GeoJSONFeatureCollection,
    summary="Listado de eventos sísmicos en formato GeoJSON",
    description=(
        "Retorna una GeoJSON FeatureCollection estándar con los sismos registrados. "
        "Por defecto devuelve los seísmos de las últimas 24 horas. "
        "Admite filtros por fecha ('desde'/'start', 'hasta'/'end'), magnitud mínima ('min_magnitud'/'min_mag'), "
        "país ('pais'/'country_id'), modo ('modo'/'mode') y paginación ('limite'/'limit', 'offset')."
    ),
    tags=["Sismología"],
)
async def get_eventos(
    desde: Optional[str] = Query(None, description="Fecha inicio ISO 8601 UTC (inclusiva)"),
    start: Optional[str] = Query(None, description="Alias en inglés para 'desde'"),
    hasta: Optional[str] = Query(None, description="Fecha fin ISO 8601 UTC (exclusiva)"),
    end: Optional[str] = Query(None, description="Alias en inglés para 'hasta'"),
    min_magnitud: Optional[float] = Query(None, description="Magnitud mínima (excluye magnitudes nulas)"),
    min_mag: Optional[float] = Query(None, description="Alias en inglés para 'min_magnitud'"),
    pais: Optional[str] = Query(None, description="Código de país ADM0_A3 de 3 letras (ej. ESP, CHL, USA)"),
    country_id: Optional[str] = Query(None, description="Alias para 'pais'"),
    modo: Optional[str] = Query(None, description="Modo operativo: 'live' o 'replay'"),
    mode: Optional[str] = Query(None, description="Alias para 'modo'"),
    limite: int = Query(500, ge=1, le=2000, description="Cantidad máxima de eventos (def: 500, máx: 2000)"),
    limit: Optional[int] = Query(None, ge=1, le=2000, description="Alias para 'limite'"),
    offset: int = Query(0, ge=0, description="Número de eventos a saltar para paginación"),
    conn: psycopg.AsyncConnection = Depends(get_db),
) -> GeoJSONFeatureCollection:
    # Resolución de alias
    desde_raw = desde if desde is not None else start
    hasta_raw = hasta if hasta is not None else end
    min_mag_val = min_magnitud if min_magnitud is not None else min_mag
    pais_raw = pais if pais is not None else country_id
    modo_val = modo if modo is not None else mode
    limite_val = limit if limit is not None else limite

    # Parseo de fechas
    desde_dt = parse_datetime(desde_raw)
    hasta_dt = parse_datetime(hasta_raw)

    # Regla de CONTRATO-API.md: Por defecto devuelve las últimas 24 horas si no se especifican fechas
    # (excepto si se consulta expresamente modo 'replay' sin filtros de tiempo para permitir ver simulaciones)
    if desde_dt is None and hasta_dt is None and (modo_val != "replay"):
        desde_dt = datetime.now(timezone.utc) - timedelta(hours=24)

    # Construcción dinámica y parametrizada de filtros SQL
    clauses: List[str] = []
    params: Dict[str, Any] = {}

    if desde_dt is not None:
        clauses.append("time >= %(desde)s")
        params["desde"] = desde_dt

    if hasta_dt is not None:
        clauses.append("time < %(hasta)s")
        params["hasta"] = hasta_dt

    if min_mag_val is not None:
        # CONTRATO-API: Magnitud nula no cumple min_mag y debe excluirse
        clauses.append("mag >= %(min_mag)s")
        params["min_mag"] = min_mag_val

    if pais_raw is not None:
        pais_clean = pais_raw.strip().upper()
        if pais_clean in ("SIN_PAIS", "NONE", "NULL", "MARITIMO"):
            clauses.append("country_id IS NULL")
        else:
            clauses.append("country_id = %(pais)s")
            params["pais"] = pais_clean

    if modo_val is not None:
        clauses.append("mode = %(modo)s")
        params["modo"] = modo_val.strip().lower()

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    async with conn.cursor() as cur:
        # 1. Obtener recuento total que cumple los filtros
        count_query = f"SELECT COUNT(*) AS total FROM v_eventos_api {where_sql};"
        await cur.execute(count_query, params)
        count_row = await cur.fetchone()
        total_eventos = count_row["total"] if count_row else 0

        # 2. Consultar fecha de última ingesta global
        last_ingestion_epoch: Optional[int] = None
        try:
            await cur.execute("SELECT MAX(ingested_at) AS last_ingest FROM eventos;")
            ingest_row = await cur.fetchone()
            if ingest_row and ingest_row.get("last_ingest"):
                last_ingestion_epoch = to_epoch_ms(ingest_row["last_ingest"])
        except Exception:
            pass

        # 3. Obtener los eventos correspondientes a la página solicitada
        query_params = dict(params)
        query_params["limite"] = limite_val
        query_params["offset"] = offset

        events_query = f"""
            SELECT
                id,
                time,
                updated,
                mag,
                mag_type,
                place,
                longitude,
                latitude,
                depth,
                country_id,
                country_name,
                status,
                tsunami,
                sig,
                mode,
                time_epoch_ms,
                updated_epoch_ms
            FROM v_eventos_api
            {where_sql}
            ORDER BY time DESC
            LIMIT %(limite)s OFFSET %(offset)s;
        """
        await cur.execute(events_query, query_params)
        rows = await cur.fetchall()

    features: List[GeoJSONFeature] = []
    for r in rows:
        # Asegurar coordenadas en orden [lon, lat, depth]
        lon = float(r["longitude"])
        lat = float(r["latitude"])
        depth = float(r["depth"]) if r["depth"] is not None else None
        coords: List[Optional[float]] = [lon, lat, depth]

        # Garantizar milisegundos epoch UTC
        t_ms = r.get("time_epoch_ms")
        if t_ms is None and r.get("time"):
            t_ms = to_epoch_ms(r["time"])
        if t_ms is None:
            t_ms = 0

        u_ms = r.get("updated_epoch_ms")
        if u_ms is None and r.get("updated"):
            u_ms = to_epoch_ms(r["updated"])
        if u_ms is None:
            u_ms = t_ms

        props = EventProperties(
            id=str(r["id"]),
            time=int(t_ms),
            updated=int(u_ms),
            mag=float(r["mag"]) if r["mag"] is not None else None,
            magType=r.get("mag_type"),
            place=r["place"] or "Sin descripción epicentral",
            country_id=r.get("country_id"),
            country_name=r.get("country_name"),
            status=r.get("status") or "automatic",
            mode=r.get("mode") or "live",
            tsunami=int(r["tsunami"]) if r.get("tsunami") is not None else 0,
            sig=int(r["sig"]) if r.get("sig") is not None else None,
        )

        features.append(
            GeoJSONFeature(
                type="Feature",
                id=str(r["id"]),
                geometry=GeoJSONPoint(type="Point", coordinates=coords),
                properties=props,
            )
        )

    now_epoch_ms = int(round(datetime.now(timezone.utc).timestamp() * 1000))
    truncated = (offset + len(features)) < total_eventos

    metadata = GeoJSONMetadata(
        total=total_eventos,
        count=len(features),
        limite=limite_val,
        offset=offset,
        generated=now_epoch_ms,
        last_ingestion=last_ingestion_epoch,
        mode=modo_val or "live",
        truncated=truncated,
    )

    return GeoJSONFeatureCollection(
        type="FeatureCollection",
        metadata=metadata,
        features=features,
    )


# ==============================================================================
# Endpoint 3: GET /api/estadisticas
# ==============================================================================

@app.get(
    "/api/estadisticas",
    response_model=EstadisticasResponse,
    summary="Métricas analíticas y agregaciones sismológicas",
    description=(
        "Calcula estadísticas consolidadas sobre el conjunto de seísmos que coinciden con los filtros: "
        "recuento total, sismo de máxima magnitud, distribuciones por magnitud y profundidad, "
        "agrupaciones por ventanas fijas de 1 hora UTC, top 10 países con más sismos y comparativa histórica."
    ),
    tags=["Analítica"],
)
async def get_estadisticas(
    desde: Optional[str] = Query(None, description="Fecha de inicio ISO 8601 UTC"),
    start: Optional[str] = Query(None, description="Alias para 'desde'"),
    hasta: Optional[str] = Query(None, description="Fecha de fin ISO 8601 UTC"),
    end: Optional[str] = Query(None, description="Alias para 'hasta'"),
    min_magnitud: Optional[float] = Query(None, description="Magnitud mínima"),
    min_mag: Optional[float] = Query(None, description="Alias para 'min_magnitud'"),
    pais: Optional[str] = Query(None, description="Código de país ADM0_A3"),
    country_id: Optional[str] = Query(None, description="Alias para 'pais'"),
    modo: Optional[str] = Query(None, description="Modo operativo: 'live' o 'replay'"),
    mode: Optional[str] = Query(None, description="Alias para 'modo'"),
    conn: psycopg.AsyncConnection = Depends(get_db),
) -> EstadisticasResponse:
    # Resolución de alias
    desde_raw = desde if desde is not None else start
    hasta_raw = hasta if hasta is not None else end
    min_mag_val = min_magnitud if min_magnitud is not None else min_mag
    pais_raw = pais if pais is not None else country_id
    modo_val = modo if modo is not None else mode

    desde_dt = parse_datetime(desde_raw)
    hasta_dt = parse_datetime(hasta_raw)

    # Por defecto, últimas 24 horas si no se especifican fechas
    if desde_dt is None and hasta_dt is None and (modo_val != "replay"):
        desde_dt = datetime.now(timezone.utc) - timedelta(hours=24)

    # Construcción de cláusulas WHERE
    clauses: List[str] = []
    params: Dict[str, Any] = {}

    if desde_dt is not None:
        clauses.append("time >= %(desde)s")
        params["desde"] = desde_dt

    if hasta_dt is not None:
        clauses.append("time < %(hasta)s")
        params["hasta"] = hasta_dt

    if min_mag_val is not None:
        clauses.append("mag >= %(min_mag)s")
        params["min_mag"] = min_mag_val

    if pais_raw is not None:
        pais_clean = pais_raw.strip().upper()
        if pais_clean in ("SIN_PAIS", "NONE", "NULL", "MARITIMO"):
            clauses.append("country_id IS NULL")
        else:
            clauses.append("country_id = %(pais)s")
            params["pais"] = pais_clean

    if modo_val is not None:
        clauses.append("mode = %(modo)s")
        params["modo"] = modo_val.strip().lower()

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    async with conn.cursor() as cur:
        # 1. Agregaciones analíticas globales y conteos de distribución
        summary_query = f"""
            SELECT
                COUNT(*) AS total_eventos,
                ROUND(AVG(mag)::numeric, 2) AS mag_promedio,
                COUNT(CASE WHEN mag IS NOT NULL AND mag < 3.0 THEN 1 END) AS mag_menor_3,
                COUNT(CASE WHEN mag >= 3.0 AND mag < 4.5 THEN 1 END) AS mag_3_a_4_5,
                COUNT(CASE WHEN mag >= 4.5 AND mag < 6.0 THEN 1 END) AS mag_4_5_a_6,
                COUNT(CASE WHEN mag >= 6.0 THEN 1 END) AS mag_mayor_igual_6,
                COUNT(CASE WHEN mag IS NULL THEN 1 END) AS mag_sin_valor,
                COUNT(CASE WHEN depth IS NOT NULL AND depth < 70.0 THEN 1 END) AS depth_someros_0_70,
                COUNT(CASE WHEN depth >= 70.0 AND depth < 300.0 THEN 1 END) AS depth_intermedios_70_300,
                COUNT(CASE WHEN depth >= 300.0 THEN 1 END) AS depth_profundos_mas_300,
                COUNT(CASE WHEN depth IS NULL THEN 1 END) AS depth_sin_valor
            FROM v_eventos_api
            {where_sql};
        """
        await cur.execute(summary_query, params)
        sum_row = await cur.fetchone() or {}

        total_eventos = int(sum_row.get("total_eventos") or 0)
        mag_promedio = float(sum_row["mag_promedio"]) if sum_row.get("mag_promedio") is not None else None

        dist_mag = DistribucionMagnitud(
            menor_3=int(sum_row.get("mag_menor_3") or 0),
            de_3_a_4_5=int(sum_row.get("mag_3_a_4_5") or 0),
            de_4_5_a_6=int(sum_row.get("mag_4_5_a_6") or 0),
            mayor_igual_6=int(sum_row.get("mag_mayor_igual_6") or 0),
            sin_magnitud=int(sum_row.get("mag_sin_valor") or 0),
        )

        dist_prof = DistribucionProfundidad(
            someros_0_70km=int(sum_row.get("depth_someros_0_70") or 0),
            intermedios_70_300km=int(sum_row.get("depth_intermedios_70_300") or 0),
            profundos_mas_300km=int(sum_row.get("depth_profundos_mas_300") or 0),
            sin_profundidad=int(sum_row.get("depth_sin_valor") or 0),
        )

        # 2. Sismo de magnitud máxima
        max_event_clauses = list(clauses)
        max_event_clauses.append("mag IS NOT NULL")
        max_where_sql = f"WHERE {' AND '.join(max_event_clauses)}"

        max_query = f"""
            SELECT id, mag, place, time, time_epoch_ms, country_id, country_name
            FROM v_eventos_api
            {max_where_sql}
            ORDER BY mag DESC, time DESC
            LIMIT 1;
        """
        await cur.execute(max_query, params)
        max_row = await cur.fetchone()

        max_magnitud_obj: Optional[EventoMaximo] = None
        if max_row:
            t_dt = max_row["time"]
            t_iso = t_dt.isoformat() if isinstance(t_dt, datetime) else str(t_dt)
            t_ms = max_row.get("time_epoch_ms")
            if t_ms is None and isinstance(t_dt, datetime):
                t_ms = to_epoch_ms(t_dt)

            max_magnitud_obj = EventoMaximo(
                id=str(max_row["id"]),
                mag=float(max_row["mag"]),
                place=max_row["place"] or "Sin descripción",
                time=t_iso,
                time_epoch_ms=int(t_ms or 0),
                country_id=max_row.get("country_id"),
                country_name=max_row.get("country_name"),
            )

        # 3. Ventanas horarias fijas de 1h UTC
        ventanas_query = f"""
            SELECT
                DATE_TRUNC('hour', time) AS hora_utc,
                COUNT(*) AS recuento,
                ROUND(AVG(mag)::numeric, 2) AS mag_promedio,
                MAX(mag) AS mag_maxima
            FROM v_eventos_api
            {where_sql}
            GROUP BY DATE_TRUNC('hour', time)
            ORDER BY hora_utc ASC;
        """
        await cur.execute(ventanas_query, params)
        ventanas_rows = await cur.fetchall()

        ventanas_horarias: List[VentanaHoraria] = []
        for vr in ventanas_rows:
            h_dt = vr["hora_utc"]
            h_iso = h_dt.isoformat() if isinstance(h_dt, datetime) else str(h_dt)
            ventanas_horarias.append(
                VentanaHoraria(
                    hora_utc=h_iso,
                    recuento=int(vr["recuento"]),
                    mag_promedio=float(vr["mag_promedio"]) if vr["mag_promedio"] is not None else None,
                    mag_maxima=float(vr["mag_maxima"]) if vr["mag_maxima"] is not None else None,
                )
            )

        # 4. Top 10 países con más sismos
        top_clauses = list(clauses)
        top_clauses.append("country_id IS NOT NULL")
        top_where_sql = f"WHERE {' AND '.join(top_clauses)}"

        top_query = f"""
            SELECT
                country_id AS pais_codigo,
                country_name AS pais_nombre,
                COUNT(*) AS recuento
            FROM v_eventos_api
            {top_where_sql}
            GROUP BY country_id, country_name
            ORDER BY recuento DESC
            LIMIT 10;
        """
        await cur.execute(top_query, params)
        top_rows = await cur.fetchall()

        top_paises: List[TopPais] = [
            TopPais(
                pais_codigo=tr["pais_codigo"],
                pais_nombre=tr["pais_nombre"],
                recuento=int(tr["recuento"]),
            )
            for tr in top_rows
        ]

        # 5. Comparativa histórica 2025 y tasa diaria normalizada
        count_2025 = 0
        try:
            await cur.execute("SELECT COUNT(*) AS c FROM eventos WHERE EXTRACT(YEAR FROM time) = 2025;")
            r_2025 = await cur.fetchone()
            if r_2025:
                count_2025 = int(r_2025["c"])
        except Exception:
            pass

    # Estimación de tasa normalizada de actividad (sismos/día)
    duracion_horas = 24.0
    if desde_dt and hasta_dt:
        duracion_horas = max(0.1, (hasta_dt - desde_dt).total_seconds() / 3600.0)
    elif len(ventanas_horarias) > 1:
        duracion_horas = float(len(ventanas_horarias))

    tasa_diaria_estimada = round((total_eventos / duracion_horas) * 24.0, 1)

    comparativa_historico = {
        "referencia_historica_2025": {
            "total_eventos_registrados_2025": count_2025,
            "tasa_estimada_normalizada_24h": tasa_diaria_estimada,
            "promedio_global_usgs_diario_referencia": 160.0,
            "interpretacion": (
                "Actividad elevada" if tasa_diaria_estimada > 220 else
                "Actividad normal" if tasa_diaria_estimada >= 100 else
                "Actividad moderada o filtro restrictivo"
            ),
        }
    }

    metadata = {
        "filtros_aplicados": {
            "desde": desde_dt.isoformat() if desde_dt else None,
            "hasta": hasta_dt.isoformat() if hasta_dt else None,
            "min_magnitud": min_mag_val,
            "pais": pais_raw,
            "modo": modo_val or "live",
        },
        "unidades": {
            "profundidad": "km",
            "tiempo": "ISO 8601 UTC / ms Unix epoch",
            "magnitud": "escala sismológica estándar USGS",
        },
        "registros_sin_magnitud": dist_mag.sin_magnitud,
        "registros_sin_profundidad": dist_prof.sin_profundidad,
        "generado_en": datetime.now(timezone.utc).isoformat(),
    }

    return EstadisticasResponse(
        total_eventos=total_eventos,
        mag_promedio=mag_promedio,
        max_magnitud=max_magnitud_obj,
        distribucion_magnitud=dist_mag,
        distribucion_profundidad=dist_prof,
        ventanas_horarias=ventanas_horarias,
        top_paises=top_paises,
        comparativa_historico=comparativa_historico,
        metadata=metadata,
    )


# ==============================================================================
# Endpoint 4: GET /api/paises
# ==============================================================================

@app.get(
    "/api/paises",
    response_model=List[PaisItem],
    summary="Catálogo de países georreferenciados",
    description="Devuelve la lista completa de países del catálogo Natural Earth (177 entidades) para poblar filtros en el frontend.",
    tags=["Catálogo"],
)
async def get_paises(
    conn: psycopg.AsyncConnection = Depends(get_db),
) -> List[PaisItem]:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT code, name_es, admin, continent, subregion
            FROM paises
            ORDER BY name_es ASC;
            """
        )
        rows = await cur.fetchall()

    return [
        PaisItem(
            code=r["code"],
            name_es=r["name_es"],
            admin=r["admin"],
            continent=r.get("continent"),
            subregion=r.get("subregion"),
        )
        for r in rows
    ]


# ==============================================================================
# Punto de Entrada para Ejecución Directa
# ==============================================================================

if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "backend.api.main:app",
        host=settings.api.host,
        port=settings.api.port,
        reload=False,
    )
