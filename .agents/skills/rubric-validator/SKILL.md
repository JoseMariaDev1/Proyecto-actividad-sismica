---
name: rubric-validator
description: >-
  Audita y valida el cumplimiento estricto de los 5 criterios de la rúbrica oficial
  (Extracción, Calidad, Modelado, Análisis, Reflexión para Sobresaliente 9-10),
  los entregables obligatorios del proyecto y las 11 pruebas de aceptación.
  Usar siempre que se quiera verificar el progreso del proyecto, preparar la memoria
  académica, o comprobar qué falta para la máxima calificación.
---

# Auditoría de Rúbrica y Entregables del Observatorio Sísmico

Esta skill proporciona la metodología, listas de control (*checklists*) y herramientas automáticas para verificar que el proyecto cumple con los requisitos del enunciado para la calificación de **Sobresaliente (9–10)**.

---

## 1. Verificación Automática de Entregables

Ejecutar el script verificador de entregables:

```powershell
python .agents/skills/rubric-validator/scripts/verificar_entregables.py
```

El script inspecciona las 6 categorías obligatorias:
1. **Infraestructura Docker**: `compose.yaml`, `Dockerfile.python`, `.env.example`, `.gitignore`.
2. **Capa de Almacenamiento**: `sql/01_init.sql`, `sql/02_seed_paises.sql`, `sql/README.md`.
3. **Backend Python**: Productor, consumidor, `spatial.py`, API FastAPI y `requirements.txt`.
4. **Frontend Angular**: Configuración, capas Leaflet, componentes y despliegue Netlify.
5. **Scripts**: Descarga histórico 2025, replay acelerado, pruebas de aceptación y benchmarks.
6. **Memoria y Documentación**: `docs/memoria.md` con 6 dimensiones de calidad y costes.

---

## 2. Los 5 Criterios de la Rúbrica para Sobresaliente (9–10)

Para consultar el desglose exhaustivo de los descriptores de la rúbrica, leer:
📄 [Criterios de Sobresaliente](./references/criterios-sobresaliente.md)

### Resumen de evidencias requeridas:

1. **Extracción (Sobresaliente: Carga + análisis de tipos)**:
   - [x] Extracción automática cada 60s del feed en tiempo real (`all_day.geojson`).
   - [x] Histórico anual 2025 (M≥4.0) particionado por meses sin sobrepasar el límite de 20.000 registros.
   - [x] Deduplicación estricta de solapes en fronteras temporales.
   - [x] Filtrado exclusivo de `type == "earthquake"` conservando el motivo de exclusión.
   - [x] Resiliencia con backoff exponencial ante 429/5xx y timeouts.

2. **Calidad (Sobresaliente: Completo + acciones)**:
   - [x] Análisis formal de las **6 dimensiones de calidad**:
     - *Completitud*: Porcentaje disponible por campo (manejo riguroso de `mag: null`).
     - *Unicidad*: Duplicados de versión y unicidad de eventos en estado actual.
     - *Validez*: Coordenadas dentro de rango WGS84, geometrías Point, tipos correctos.
     - *Consistencia*: Coherencia temporal (`time <= updated`), integridad referencial con `paises`.
     - *Actualidad*: Latencia entre ocurrencia, actualización USGS e ingesta local.
     - *Exactitud*: Limitaciones del mapa simplificado y contrastabilidad de fuentes.
   - [x] Tabla de **cuarentena** (`eventos_cuarentena`) para datos no tratables.
   - [x] Justificación técnica de no rellenar nulos con cero y admisión de magnitudes/profundidades negativas.

3. **Modelado (Sobresaliente: Modelo optimizado)**:
   - [x] 5 servicios separados en Docker Compose (`producer`, `kafka`, `consumer`, `postgres`, `api`).
   - [x] Esquema con hechos y dimensiones: `paises`, `eventos_raw`, `eventos`, `eventos_versiones`, `eventos_cuarentena`, `estado_productor`.
   - [x] Idempotencia estricta en el consumidor (soporte para at-least-once de Kafka).
   - [x] Indexación B-Tree estratégica y spatial indexing con STRtree ($O(\log N)$).

4. **Análisis (Sobresaliente: Análisis + insights)**:
   - [x] Agregaciones en ventanas horarias fijas de 1 hora UTC.
   - [x] Distribuciones de magnitud y profundidad.
   - [x] Comparación histórica equivalente (2025 vs últimas 24 horas).
   - [x] Al menos **tres conclusiones fundamentadas con cifras, filtros y periodos**.

5. **Reflexión (Sobresaliente: Excelente + propuestas)**:
   - [x] Justificación teórica de complejidad asintótica Big-O de 3 operaciones clave.
   - [x] Benchmarks empíricos midiendo tiempo de CPU y memoria RAM con 3 tamaños de muestra.
   - [x] Estimación desglosada de costes reales (hardware, consumo eléctrico, cloud, mantenimiento y desarrollo).
   - [x] Propuesta de escalabilidad técnica para soportar 100 millones de registros.

---

## 3. Las 11 Pruebas de Aceptación

Para consultar los escenarios detallados de prueba:
📄 [Guía de Pruebas de Aceptación](./references/pruebas-aceptacion.md)

Verificar periódicamente ejecutando:
```powershell
python scripts/probar_aceptacion.py
```
