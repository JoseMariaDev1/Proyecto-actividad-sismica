# Proyecto: Observatorio de actividad sísmica

**Sistemas de Big Data · Consolidación de las sesiones 1–8 · RA1**  
**Versión del enunciado: 27 de octubre de 2026 · revisión 2 (Docker, HTTPS y evidencias de calidad)**

## 1. El reto

Construye un sistema que recoja datos de terremotos, los procese y permita responder: **¿dónde se está registrando actividad sísmica y cómo se compara con un periodo histórico equivalente?**

El sistema combinará un histórico, información reciente y un catálogo geográfico. Deberás demostrar extracción automática, calidad, integración, modelado, análisis y reflexión sobre costes y complejidad. El mapa es una parte del resultado: no basta con representar directamente la respuesta de USGS.

Este proyecto adapta el contexto del ejercicio de supermercados de la sesión 8. Conserva sus cinco criterios y niveles de rúbrica, pero su desarrollo requiere trabajo previo: no se plantea realizar toda la infraestructura en los 90 minutos del ejercicio original. La fecha, modalidad individual o por equipos y encaje en las partes de evaluación se comunicarán en clase. No se modifican aquí los porcentajes generales publicados (test 30 %, ejercicio práctico 50 %, mini-ETL 20 %).

## 2. Arquitectura obligatoria

| Componente | Tecnología y responsabilidad | Ubicación |
|---|---|---|
| Productor | Python + aiokafka; extracción USGS y publicación de novedades | Contenedor Docker local |
| Broker | Apache Kafka; transporte y retención de mensajes | Contenedor Docker local |
| Consumidor | Python + aiokafka; validación, limpieza, enriquecimiento y escritura | Contenedor Docker local |
| Almacenamiento | PostgreSQL; datos preparados, originales y estado persistente | Contenedor Docker local |
| API | Python + FastAPI; consulta de datos ya procesados | Contenedor Docker local |
| Túnel | ngrok; acceso HTTPS a la API | Agente en el equipo o contenedor Docker |
| Panel | Angular + Leaflet; mapa y análisis | Netlify |

Es obligatorio ejecutar productor Python, consumidor Python, Kafka, PostgreSQL y API FastAPI en cinco servicios separados de Docker Compose, en el equipo del alumno. La entrega debe permitir levantarlos conjuntamente con `docker compose up --build -d`. «Local» indica el equipo anfitrión: no significa ejecutar productor o consumidor fuera de Docker. Cada servicio Python tendrá una imagen reproducible; se puede compartir una imagen con comandos de inicio diferentes. Configura comprobaciones de salud y reintentos: el orden de arranque por sí solo no garantiza que Kafka o PostgreSQL estén preparados. El frontend se compila y publica como SPA. El navegador del visitante descarga Angular desde Netlify y consulta la API mediante ngrok. Kafka y PostgreSQL no se publican por el túnel.

No se exige Spark, Flink, Kubernetes, aprendizaje automático ni un servidor cloud permanente. Las ventanas pueden calcularse con Python y SQL. El productor y el consumidor siguen trabajando aunque el panel esté cerrado.

## 3. Material de partida proporcionado

- Este enunciado y la guía `README.md`.
- Proyecto Angular de apoyo ejecutable, con dependencias fijadas y archivo de bloqueo.
- Catálogo `frontend/public/datos/paises.geojson`: límites y atributos de Natural Earth.
- Cuatro eventos ficticios para verificar el mapa sin backend.
- Configuración para conectar después el mapa a vuestra API y publicar en Netlify.
- Contrato mínimo de la API en `CONTRATO-API.md`.
- Fuentes, licencias y huella del catálogo en `FUENTES-Y-LICENCIAS.md`.

El mapa de apoyo ya representa fondo, fronteras y terremotos. Debes implementar el pipeline, la persistencia, la API, los filtros, los gráficos y las métricas, y documentar los resultados en una memoria o notebook. La muestra ficticia no sustituye la demostración con datos reales.

## 4. Fuentes de información

### 4.1 Datos recientes

Consulta mediante HTTP GET, aproximadamente cada 60 segundos:

https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson

Es una ventana móvil de las últimas 24 horas, actualizada cada minuto; no es el día natural anterior ni una conexión push. Cada respuesta vuelve a contener toda la ventana. La publicación de un terremoto puede tener retraso y sus datos pueden revisarse.

Identifica los campos `id`, `properties.time`, `properties.updated`, `properties.mag`, `properties.magType`, `properties.type`, `properties.place` y `geometry.coordinates`. Las coordenadas son **longitud, latitud, profundidad en km**. Los tiempos son milisegundos desde Unix epoch.

Documenta respuesta, tipos, unidades, campos opcionales, frecuencia, errores y latencia. Filtra `properties.type == "earthquake"` para evitar tratar explosiones u otros eventos como terremotos. Conserva el motivo de exclusión.

### 4.2 Histórico

Obtén un año completo mediante la API del catálogo, con un alcance manejable. Propuesta de partida: **año 2025, ámbito mundial, magnitud igual o superior a 4 y tipo earthquake**.

Ejemplo de descarga de un mes:

https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime=2025-01-01T00:00:00Z&endtime=2025-02-01T00:00:00Z&minmagnitude=4&eventtype=earthquake&orderby=time-asc

Divide el año en meses; si una consulta supera el máximo de 20.000 resultados, subdivídela en intervalos menores. No resuelvas el exceso truncando silenciosamente la respuesta. Los límites temporales de la fuente pueden incluir ambos extremos: deduplica los eventos compartidos entre intervalos. Guarda consultas, fecha de extracción y número de registros.

Descarga una vez y reutiliza los archivos. Puedes acotar una zona en lugar del mundo, siempre que documentes los filtros y los mantengas iguales en la comparación. El histórico es una instantánea del catálogo en la fecha de extracción, no un registro completo de todas sus revisiones pasadas.

### 4.3 Catálogo geográfico

Usa la copia de Natural Earth entregada. Cada entidad contiene uno o varios polígonos (`Polygon` o `MultiPolygon`) y atributos como `ADM0_A3`, `NAME_ES`, `ADMIN`, `CONTINENT` y `SUBREGION`.

Integra cada terremoto mediante una operación espacial de punto dentro de polígono; no extraigas el país a partir del texto de `place`. Puedes utilizar GeoPandas/Shapely. Mantén ambas fuentes en coordenadas geográficas compatibles (WGS84/EPSG:4326) y documenta la regla para puntos sobre una frontera o con varias coincidencias.

Utiliza `ADM0_A3` como identificador del catálogo después de comprobar unicidad; no presupongas que todos sus valores son códigos ISO oficiales. Conserva una categoría «Sin país asignado»: puede deberse a un evento marítimo, simplificación de costas o falta de cobertura. No lo clasifiques automáticamente como error ni lo atribuyas al país más cercano.

## 5. Extracción e ingesta

1. Configura el productor con variables de entorno para dirección Kafka, topic y frecuencia.
2. Conserva el GeoJSON original y los metadatos de extracción antes de transformarlo. Evita almacenar indefinidamente copias idénticas; define una retención y registra las consultas.
3. Para cada evento compara `id` y `updated` con el estado persistente. Publica los nuevos y las revisiones posteriores; omite versiones ya publicadas.
4. Usa el identificador del evento como clave Kafka. Incluye en el mensaje `source`, `ingested_at`, `mode` (`live` o `replay`) y el evento original.
5. Espera la confirmación de Kafka antes de marcar la versión como publicada. Si el proceso cae entre ambas operaciones puede reenviar un mensaje: el consumidor debe tolerarlo.
6. Gestiona timeout, HTTP 429/5xx, reintentos con espera progresiva y errores de JSON. Registra el error sin borrar el estado válido anterior.

No confundas «no aparece en la siguiente ventana» con «USGS lo ha eliminado»: puede haber envejecido más allá de las 24 horas. Mantén el histórico almacenado. La reconciliación exhaustiva de eventos eliminados, fusionados o revisados cuando ya están fuera del feed es una ampliación; documenta esta limitación del alcance mínimo. Tras una parada superior a 24 horas, explica cómo recuperar el hueco con el catálogo histórico.

## 6. Calidad y transformación

El consumidor debe aplicar reglas explícitas de validación y transformación. El análisis de calidad se documentará en **un apartado de la memoria o en un notebook**, con código o consultas, resultados antes/después y explicación de las decisiones.

**No se exige que el consumidor genere documentos, ni crear un script de generación automática de informes, ni un panel de calidad en Angular.** Tampoco hace falta un archivo de calidad separado de la memoria. La automatización de informes y su visualización en el panel son ampliaciones opcionales; no son condiciones para alcanzar el nivel máximo de la rúbrica.

La tarea original de la sesión 8 pide calcular completitud, identificar duplicados, detectar valores anómalos y proponer acciones de limpieza. Su rúbrica valora cuatro o más dimensiones para notable y un análisis completo con acciones para sobresaliente. Para orientar ese análisis, considera las siguientes dimensiones; cuando no puedas verificar alguna, justifica la limitación:

| Dimensión | Evidencia esperada |
|---|---|
| Completitud | Porcentaje disponible por campo; magnitud o localización descriptiva ausente |
| Unicidad | Duplicados de versión y unicidad de eventos en el estado actual |
| Validez | Tipos, fechas parseables, coordenadas finitas en rango y geometría Point |
| Consistencia | Claves geográficas, coherencia de unidades y secuencia de revisiones |
| Actualidad | Tiempo de evento, actualización USGS e ingesta; retrasos observados |
| Exactitud | Qué se puede contrastar y qué no; limitaciones de USGS y del mapa simplificado |

No rellenes indiscriminadamente nulos con cero. Una magnitud negativa no es automáticamente un error; una profundidad negativa tampoco debe rechazarse sin estudiar su significado. Señala anomalías y justifica las reglas aplicadas. Si un registro no puede tratarse, consérvalo en cuarentena con motivo y referencia al original. Los casos de prueba artificialmente dañados deben quedar separados e identificados.

Convierte las fechas a UTC y conserva sus unidades. Separa el tiempo de ocurrencia del tiempo de procesamiento. Registra qué transformaciones cambian los datos y cuántos registros afectan.

## 7. Integración y modelado

Presenta un modelo conceptual, lógico y físico. Como orientación:

- **Hecho evento actual:** una fila por `event_id`, con magnitud, profundidad, fechas y claves de dimensiones.
- **Dimensiones:** fecha y país/región; puedes añadir ubicación o tipo de magnitud si lo justificas.
- **Historial de versiones:** una fila por `(event_id, updated)` con los cambios observados y el original.
- **Estado de ingesta y calidad:** última versión publicada, consultas y rechazos.

No es obligatorio copiar esta estructura, pero sí explicar el grano, las claves, relaciones e índices. La integración debe unir terremotos con atributos del catálogo geográfico; histórico y feed son dos accesos a USGS, no sustituyen esa segunda fuente.

Al recibir una revisión, actualiza el estado actual solo si es más reciente. Conserva la versión recibida sin sobrescribir una posterior. Guarda los cambios de forma transaccional y confirma el offset después de la escritura. Si se repite el mensaje tras un fallo, las restricciones únicas y el upsert deben impedir que aumente el recuento.

No se exige una transacción distribuida Kafka–PostgreSQL: implementa procesamiento al menos una vez con escritura idempotente. El orden por clave facilita el tratamiento, pero no sustituye la comparación de versiones.

## 8. Análisis y panel

El panel consultará vuestra API, no directamente USGS. Debe incluir:

1. **Mapa interactivo** con fondo, fronteras, círculos y ficha del terremoto. Tamaño por magnitud, color por profundidad, leyenda y tratamiento visible de nulos.
2. **Recuentos por país o subregión y ventanas fijas de una hora UTC**, usando el tiempo del evento. Incluye «Sin país asignado».
3. **Distribuciones de magnitud y profundidad**, indicando registros sin valor.
4. **Comparación histórica**: por ejemplo, recuento de las últimas 24 horas con magnitud ≥4 frente a la media diaria de 2025 bajo los mismos filtros geográficos y de tipo. El denominador histórico incluye días con cero eventos. Explica que el último periodo aún puede estar incompleto por retrasos.
5. **Filtros** de fecha, magnitud y país/región, aplicados de forma coherente al mapa y los gráficos.
6. **Estado del sistema:** último acceso correcto a la API, última ingesta correcta de USGS, periodo consultado y aviso cuando los datos estén desactualizados o el backend no responda.
7. **Tabla consultable** de eventos como alternativa al mapa y al color.

Las revisiones pueden cambiar magnitud, ubicación o fecha. Recalcula las ventanas afectadas o calcula las agregaciones desde la tabla de estado actual: no incrementes un contador por cada mensaje sin distinguir revisiones.

Redacta al menos **tres conclusiones fundamentadas**, con cifras, filtros y periodo. Compara muestras equivalentes. La cobertura de detección y los tipos de magnitud pueden variar; no presentes estas estadísticas como predicción de terremotos ni como una evaluación de riesgo.

## 9. Despliegue y funcionamiento

- Incluye `compose.yaml`, dependencias fijadas, inicialización de la base y `.env.example` sin credenciales.
- Configura volúmenes persistentes para los datos y una retención limitada de Kafka.
- Usa nombres de servicio Docker dentro de Compose; `localhost` dentro de un contenedor no apunta al equipo anfitrión. Documenta los listeners de Kafka si accedes también desde el host.
- Expón solo la API de consulta. Si ngrok se ejecuta en el equipo, publica el puerto de la API en el host, preferiblemente `127.0.0.1:8000:8000`, y ejecuta `ngrok http 8000`.
- Si ngrok se ejecuta en un contenedor de la misma red Compose, utiliza `ngrok http http://api:8000`, siendo `api` el nombre del servicio. En este caso no es necesario publicar el puerto de la API en el host para que el túnel funcione.
- FastAPI/Uvicorn debe escuchar en `0.0.0.0:8000` dentro del contenedor para recibir conexiones desde el túnel o el puerto publicado.
- ngrok proporciona una URL pública HTTPS y gestiona su certificado, también en el plan gratuito dentro de sus límites. No instales un certificado en FastAPI: la API puede atender HTTP en la red local de Docker. El tramo navegador–ngrok usa HTTPS, el tramo ngrok–agente utiliza un túnel cifrado y el tramo agente–API puede usar HTTP. Angular debe utilizar siempre la URL pública HTTPS.
- Publica Angular en Netlify e indica la URL HTTPS de ngrok en `public/config.json` antes de compilar.
- Autoriza en CORS el origen exacto de Netlify y el de desarrollo. Atiende `OPTIONS` y permite `ngrok-skip-browser-warning` si el frontend la utiliza. CORS no es autenticación.
- No expongas rutas de administración, secretos, base de datos o broker. No incluyas el authtoken de ngrok en Angular ni en Git.
- El mapa consultará la API cada 60 segundos. El productor consultará USGS por su cuenta cada 60 segundos.

El equipo, los contenedores y el túnel deben permanecer activos durante la demostración. Al apagarlos, Netlify seguirá sirviendo la interfaz pero no habrá datos nuevos. Se evalúa esta limitación y el tratamiento del error, no disponibilidad 24/7. Las cuentas gratuitas tienen cuotas; evitad refrescos innecesarios y comprobad sus condiciones al desplegar.

## 10. Complejidad, rendimiento y costes

Justifica al menos tres estructuras u operaciones: búsqueda de versiones por identificador, integración geográfica y agregación por ventanas. Distingue coste medio y peor caso cuando corresponda.

Mide tiempo y memoria con al menos tres tamaños de entrada, documentando equipo, procedimiento y resultados. Si replicas datos para una prueba de escala, márcalos como sintéticos y mantenlos fuera del análisis real. Compara una búsqueda secuencial con diccionario o una consulta sin/con índice, y razona qué ocurriría con 100 millones de registros.

Incluye costes de hardware, electricidad, almacenamiento, transferencia, mantenimiento y tiempo de desarrollo. Una cuota cloud gratuita no equivale a coste total cero. Presenta supuestos y una propuesta de escalado; no hace falta contratar servicios. Puedes estimar ROI si defines un beneficio medible y justificable; no inventes beneficios económicos del observatorio.

## 11. Pruebas de aceptación y demostración

| Prueba | Resultado esperado |
|---|---|
| Recibir un evento nuevo | Una fila actual, visible en API, mapa y análisis |
| Reenviar la misma versión | No aumenta el número de terremotos |
| Recibir una versión posterior | Cambian los datos actuales y las agregaciones afectadas |
| Recibir después una versión antigua | No sustituye a la más reciente |
| Magnitud nula | Se conserva con tratamiento documentado y se visualiza como ND |
| Coordenadas inválidas | Cuarentena y motivo; no aparecen puntos inventados |
| Evento marítimo | Sin país asignado; permanece en el análisis |
| Reiniciar consumidor | Reanuda sin duplicar los efectos ya persistidos |
| Cerrar el túnel | El panel muestra el fallo y conserva/identifica la última lectura |
| Volver a abrir el túnel | Se recuperan las consultas automáticamente |
| Reproducción histórica | Procesa por Kafka sin mezclarla con datos live |

Para asegurar una demostración con actividad, implementa una reproducción acelerada de una selección histórica ordenada por fecha. Mantén el tiempo original y añade el de reproducción. Utiliza topic y esquema/tablas separados o un mecanismo equivalente de aislamiento. Etiqueta claramente «REPRODUCCIÓN». El productor de replay reutiliza el procesamiento del consumidor. Incluye casos controlados de duplicado y revisión.

## 12. Entregables

- Repositorio con código, Dockerfile(s), `compose.yaml` con los cinco servicios obligatorios, dependencias, `.env.example` e instrucciones reproducibles.
- URL del panel y procedimiento para activar el backend/túnel durante la defensa.
- Diccionario de datos y registro de consultas y procedencia.
- Apartado de calidad en la memoria o en un notebook: código o consultas, resultados antes/después, decisiones y registros de ejemplo. No se exige un documento separado ni generación automática.
- Modelo conceptual/lógico/físico, SQL y justificación de índices.
- Análisis con al menos tres conclusiones y capturas de los filtros usados.
- Informe de complejidad, mediciones, costes y propuestas de mejora.
- Evidencias de las pruebas de aceptación y reproducción histórica.
- Explicación individual del flujo completo y de una decisión técnica propia.

No incluyas `node_modules`, credenciales, volúmenes binarios ni grandes conjuntos descargables en Git. Conserva datos originales en una ubicación documentada e incluye un procedimiento para regenerarlos.

## 13. Evaluación

Se conservan los descriptores de la rúbrica de la sesión 8:

| Criterio | Insuficiente (0–4) | Suficiente (5–6) | Notable (7–8) | Sobresaliente (9–10) |
|---|---|---|---|---|
| Extracción | No carga datos | Carga básica | Carga + exploración | Carga + análisis tipos |
| Calidad | No analiza | Análisis parcial | 4+ dimensiones | Completo + acciones |
| Modelado | No combina | Join básico | Modelo correcto | Modelo optimizado |
| Análisis | No realiza | 1–2 análisis | 3+ análisis | Análisis + insights |
| Reflexión | No reflexiona | Reflexión básica | Buena reflexión | Excelente + propuestas |

En este proyecto, sus evidencias son:

| Criterio | Evidencias concretas |
|---|---|
| Extracción | Histórico, feed y catálogo; tipos, unidades, límites y automatización |
| Calidad | Apartado en memoria o notebook con comprobaciones de las dimensiones de calidad, resultados antes/después, acciones justificadas y limitaciones. Se aplican los niveles de la rúbrica; no se exige automatizar el informe |
| Modelado | Integración geográfica, grano y claves, revisiones, idempotencia y optimización |
| Análisis | Ventanas, distribuciones, comparación equivalente y conclusiones |
| Reflexión | Complejidad, memoria, escalado, costes, limitaciones y mejoras |

El uso del mapa entregado no sustituye las evidencias anteriores. No se exige desarrollar un motor cartográfico desde cero ni obtener mejores calificaciones mediante más complejidad de infraestructura.
