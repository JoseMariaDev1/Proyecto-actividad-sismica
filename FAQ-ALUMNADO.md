# FAQ del alumnado: Observatorio de actividad sísmica

**Guía de apoyo con ejemplos · 27 de octubre de 2026 · revisión: evidencias de calidad**

Lee primero las preguntas 1–5 y sigue el itinerario de la pregunta 6. Consulta el resto cuando llegues a esa parte. Esta guía aclara el enunciado: no añade requisitos ni sustituye su rúbrica.

**Todos los eventos, cantidades y resultados de los ejemplos de esta guía son ficticios.** Las horas se expresan en UTC. No representan actividad sísmica real.

## A. Entender qué hay que construir

### 1. ¿Qué tenemos que hacer, explicado de forma sencilla?

Una aplicación que recoja información de terremotos, compruebe sus datos, los guarde y permita explorarlos en un mapa y en gráficos.

Por ejemplo: aparece un terremoto en USGS, nuestro productor lo recoge, Kafka lo transporta, el consumidor lo prepara y guarda, y Angular lo muestra al consultar nuestra API.

El resultado debe permitir contestar preguntas como:

- ¿Cuántos eventos registrados hay en cada país o zona durante un periodo?
- ¿Cómo se distribuyen sus magnitudes y profundidades?
- ¿El recuento reciente es mayor o menor que la media de un periodo histórico comparable?

No estamos construyendo un sistema que prediga terremotos.

### 2. ¿Para qué sirve cada programa? ¿No hacen todos lo mismo?

| Pieza | Su trabajo | Ejemplo |
|---|---|---|
| Productor Python | Recoger novedades de USGS y publicarlas | «He encontrado una nueva versión del evento E1» |
| Kafka | Conservar y transportar mensajes | Guarda el mensaje hasta que el consumidor lo lea |
| Consumidor Python | Validar, transformar, enriquecer y persistir | Convierte fechas, asigna país y guarda E1 |
| PostgreSQL | Almacenar el resultado consultable | Conserva la versión actual y las versiones recibidas |
| API FastAPI | Responder consultas sobre los datos preparados | «Dame los terremotos de las últimas 24 horas» |
| Angular + Leaflet | Presentar los resultados | Dibuja los puntos, filtros, tabla y gráficos |
| ngrok | Hacer accesible la API local por HTTPS | Proporciona una dirección pública para la API |
| Netlify | Servir los archivos de Angular | Permite abrir el panel desde otro equipo |

**El consumidor prepara los datos. La API los consulta.** Son procesos separados: abrir el mapa no debería ser necesario para que se sigan recogiendo terremotos.

### 3. ¿Qué viene hecho y qué tenemos que programar?

| Ya se proporciona | Debes desarrollar |
|---|---|
| Proyecto Angular con un mapa básico | Filtros, tabla accesible, gráficos y análisis |
| Fronteras de países en GeoJSON | Integración geográfica en Python |
| Cuatro puntos ficticios de demostración | Extracción y tratamiento de datos reales |
| Conexión configurable a `/api/eventos` | Backend que implemente esa ruta y las estadísticas |
| Contrato de respuesta de la API | PostgreSQL, tablas, claves y consultas |
| Configuración del frontend para Netlify | Dockerfile(s), Compose y puesta en marcha del backend |
| Enunciado, rúbrica y esta guía | Memoria o notebook con evidencias, pruebas y defensa del trabajo |

Que el mapa inicial ya funcione no significa que el proyecto esté terminado. Es el material de apoyo para no dedicar todo el tiempo a programar la cartografía.

### 4. ¿Debe ir todo en Docker?

Estos **cinco servicios son obligatorios en Docker Compose**: productor, Kafka, consumidor, PostgreSQL y API.

Cada uno se ejecuta en un contenedor separado. Productor, consumidor y API pueden compartir una imagen Python, arrancando comandos diferentes. El equipo del alumno es el anfitrión de Docker.

Angular se puede desarrollar con `npm start` en el equipo y se publica como SPA en Netlify. ngrok puede instalarse en el equipo o ejecutarse en otro contenedor.

El comando de entrega será:

```bash
docker compose up --build -d
```

**Ese comando solo funcionará cuando hayas creado tu `compose.yaml` y las imágenes correspondientes.** El paquete inicial no incluye el backend resuelto.

### 5. ¿Necesitamos Spark, Flink, Kubernetes o inteligencia artificial?

No. Utiliza Python, aiokafka, Kafka, PostgreSQL, FastAPI y el frontend entregado. Las agregaciones pueden hacerse con Python y SQL.

La dificultad que se evalúa está en entender y tratar los datos: repetir un mensaje sin duplicar resultados, combinar fuentes, justificar decisiones y extraer conclusiones.

## B. Empezar sin intentar hacerlo todo a la vez

### 6. ¿En qué orden conviene trabajar?

Avanza hasta conseguir una evidencia visible en cada paso:

| Paso | Trabajo | Cómo comprobar que funciona |
|---|---|---|
| 1 | Ejecuta el frontend entregado en modo demo | Ves cuatro puntos ficticios y fronteras |
| 2 | Descarga una respuesta de USGS y explora su JSON | Puedes explicar un evento y sus campos |
| 3 | Levanta Kafka y un productor y consumidor mínimos en Docker | Un mensaje de prueba llega al log del consumidor |
| 4 | Añade PostgreSQL, tablas y escritura del consumidor | El evento aparece en una consulta SQL |
| 5 | Implementa duplicados y revisiones | La secuencia de la pregunta 12 da los resultados esperados |
| 6 | Integra el catálogo de países y la calidad | El evento tiene país o motivo de no asignación |
| 7 | Implementa la API | `/api/eventos` devuelve GeoJSON desde PostgreSQL |
| 8 | Conecta Angular a la API | Ves los eventos de tu base de datos |
| 9 | Incorpora el histórico, filtros y estadísticas | Puedes justificar tres resultados |
| 10 | Publica Angular y abre el túnel | Otro dispositivo accede al panel y consulta los datos |
| 11 | Prepara reproducción, mediciones e informe | Puedes repetir la demostración sin depender de nuevos sismos |

En el paso 3 puede usarse un evento ficticio. Después debes sustituirlo por el productor real. No esperes al despliegue para comprobar la lógica de datos.

### 7. ¿Qué debería funcionar en una primera versión pequeña?

Un evento debe completar el recorrido: publicación en Kafka, consumo, escritura en PostgreSQL, consulta por la API y representación en Angular.

Después añade calidad, revisiones, catálogo, histórico y análisis. Esta primera versión es un punto de control, **no la entrega final**.

## C. Extraer y entender los datos

### 8. ¿`all_day.geojson` contiene los datos del día anterior?

No. Contiene una ventana móvil de las últimas 24 horas. Si consultas a las 16:00, cubre aproximadamente desde las 16:00 de ayer hasta ahora.

Cada consulta devuelve la ventana completa. Si hoy recibes 100 eventos y un minuto después 101, eso no significa que hayan ocurrido 101 terremotos nuevos.

El productor consulta aproximadamente cada 60 segundos. La fuente no nos envía automáticamente cada evento por una conexión persistente.

### 9. ¿Qué significa cada campo de un terremoto?

Ejemplo abreviado de GeoJSON, con datos ficticios:

```json
{
  "type": "Feature",
  "id": "demo-E1",
  "geometry": {
    "type": "Point",
    "coordinates": [-3.7, 40.4, 12]
  },
  "properties": {
    "type": "earthquake",
    "mag": 4.2,
    "magType": "mw",
    "place": "Localización ficticia",
    "time": 1793109600000,
    "updated": 1793109900000
  }
}
```

| Campo | Significado |
|---|---|
| `id` | Identifica el evento; se conserva en sus revisiones |
| `time` | Cuándo ocurrió, en milisegundos Unix |
| `updated` | Cuándo se actualizó esa versión en la fuente |
| `mag` | Magnitud; puede faltar o ser nula |
| `magType` | Tipo de magnitud; no todos los valores usan la misma escala |
| `coordinates[0]` | Longitud: −3,7 |
| `coordinates[1]` | Latitud: 40,4 |
| `coordinates[2]` | Profundidad: 12 km |

En Python puedes convertir un timestamp así:

```python
from datetime import datetime, timezone
fecha = datetime.fromtimestamp(1793109600000 / 1000, tz=timezone.utc)
```

Dividir por 1.000 es necesario porque la función recibe segundos. No confundas `time` con `updated` ni con la hora a la que tú descargaste el registro.

### 10. ¿Qué hace el productor en cada consulta?

Para cada evento consulta el estado persistido de versiones ya publicadas:

| Situación | Decisión |
|---|---|
| No conoce el identificador | Publica el evento |
| Conoce el identificador y `updated` es igual | No vuelve a publicar esa versión |
| `updated` es posterior al que conoce | Publica la revisión |
| `updated` es anterior al que conoce | No publica una versión atrasada como novedad |

Después de publicar, espera la confirmación de Kafka. Solo entonces guarda la versión como publicada. Si el programa se interrumpe entre esos dos pasos, puede reenviar el mensaje al reiniciar. Por eso también necesitamos protección contra duplicados en el consumidor.

Un diccionario de Python puede acelerar las búsquedas, pero el estado importante debe sobrevivir a un reinicio: guardarlo solo en RAM no basta.

### 11. ¿Para qué sirve Kafka si podríamos guardar directamente en la base?

Separa el ritmo de recogida del ritmo de procesamiento.

Ejemplo: el productor recoge eventos y el consumidor se detiene durante dos minutos. Kafka conserva los mensajes dentro de su retención y el consumidor puede continuar después desde su posición confirmada.

Kafka es un requisito de esta práctica. Para algunos sistemas pequeños podrían existir arquitecturas más sencillas; aquí se evalúa que sepas construir y explicar este flujo.

## D. El ejemplo más importante: duplicados y revisiones

### 12. ¿Qué debería pasar si llega varias veces el mismo terremoto?

Supón que la base comienza vacía. Llega esta secuencia, con todas las horas en el mismo día UTC:

| Mensaje recibido | `id` | `updated` | Magnitud | Eventos actuales tras procesarlo | Versiones distintas guardadas |
|---|---|---|---|---:|---:|
| Primera versión | E1 | 10:05 | 4,2 | 1 | 1 |
| Repetición idéntica | E1 | 10:05 | 4,2 | 1 | 1 |
| Revisión posterior | E1 | 10:09 | 4,6 | 1 | 2 |
| Repetición de la versión antigua | E1 | 10:05 | 4,2 | 1 | 2 |
| Otro terremoto | E2 | 10:12 | 3,1 | 2 | 3 |

**Resultado final:** dos terremotos actuales. E1 tiene magnitud 4,6 y E2 tiene magnitud 3,1. Hay tres versiones distintas observadas en total.

No son cinco terremotos por haber recibido cinco mensajes. Tampoco debes devolver E1 a magnitud 4,2 al recibir tarde la versión antigua.

En la implementación real, `updated` contiene un timestamp completo, no solo la hora de esta tabla.

### 13. ¿Qué significa que el consumidor sea idempotente?

Que procesar de nuevo el mismo mensaje no cambia otra vez el resultado.

Ejemplo: el consumidor guarda E1 en PostgreSQL y se apaga antes de confirmar el offset en Kafka. Al reiniciar, vuelve a recibir E1. Una restricción única y una escritura controlada impiden crear otra fila actual.

Orden básico:

1. Validar y preparar los datos.
2. Guardar cambios y versión dentro de una transacción de PostgreSQL.
3. Confirmar la transacción.
4. Confirmar el offset de Kafka.

Si el mensaje no es válido, registra la cuarentena de forma duradera antes de avanzar. No lo pierdas silenciosamente ni bloquees indefinidamente toda la cola por un registro defectuoso.

### 14. ¿Qué es un offset? ¿Es el identificador del terremoto?

No. El offset es la posición de un mensaje **dentro de una partición de Kafka**. El `id` de USGS identifica el terremoto.

Un mismo terremoto puede tener varias versiones en diferentes offsets. Para reanudar la lectura se utiliza el offset; para evitar duplicar terremotos se utilizan el identificador y la versión.

### 15. ¿Si un evento desaparece del feed, lo borro de la base?

No. Puede haber salido de la ventana de 24 horas sin haber sido eliminado por USGS.

Ejemplo: un terremoto ocurrido ayer a las 10:00 deja de aparecer cuando ya han pasado más de 24 horas. Debe seguir en tu almacenamiento histórico, aunque deje de mostrarse al filtrar «últimas 24 horas».

El alcance mínimo no resuelve exhaustivamente todas las retiradas o fusiones de eventos del catálogo. Explica esa limitación en el informe.

## E. Limpieza, catálogo y almacenamiento

### 16. ¿Qué hay que limpiar si los datos vienen de un organismo oficial?

Limpiar también significa validar y decidir cómo representar ausencias, revisiones y unidades. No significa que tengas que encontrar errores a la fuerza.

| Caso ficticio | Tratamiento razonable |
|---|---|
| `mag: null` | Conservar nulo; mostrar ND; excluir de cálculos que necesitan magnitud e indicar cuántos se excluyen |
| Magnitud −0,5 | No descartarla solo por ser negativa |
| Latitud 145° | Coordenada inválida: cuarentena con motivo |
| Mismo `id` y `updated` | Duplicado de versión; no sumar un evento |
| Misma identidad, versión posterior | Actualizar el estado actual |
| Sin país asignado | Conservarlo y explicar que puede estar en el mar |
| Timestamp en milisegundos | Convertir correctamente a UTC, conservando el original |
| Tipo de evento distinto de earthquake | Excluir del análisis sísmico definido y registrar la razón |

No cambies una profundidad negativa o un valor poco habitual sin investigar su significado.

### 17. ¿Dónde hago el análisis de calidad? ¿Tengo que programar un generador de informes?

**Basta con un apartado de la memoria o un notebook. No tienes que programar un generador de informes ni un panel de calidad.** Tampoco hace falta entregar un archivo separado solo para calidad.

La tarea original pedía calcular completitud, identificar duplicados, detectar anomalías y proponer acciones de limpieza. La rúbrica valora cuatro o más dimensiones para notable y un análisis completo con acciones para sobresaliente; no exige automatizar la elaboración del documento.

Distingue dos trabajos:

| Durante el funcionamiento del sistema | Al preparar la entrega |
|---|---|
| El consumidor valida, transforma, guarda y registra los rechazos | El alumno ejecuta consultas o código y documenta los resultados |
| La cuarentena conserva el original y el motivo del rechazo | La memoria o notebook explica decisiones, efectos y limitaciones |

Puedes consultar PostgreSQL desde un cliente SQL o analizar los datos originales y preparados con Python. Si usas un notebook fuera de Docker, documenta la conexión local o la exportación utilizada; el productor y el consumidor del sistema siguen ejecutándose en contenedores.

**Ejemplo de trabajo:** cuenta cuántos registros tienen magnitud y cuántos no, calcula el porcentaje, pega la consulta o el código y su resultado, y explica qué haces con los nulos. Repite el proceso para las otras comprobaciones. No basta con afirmar «los datos son correctos» sin evidencias.

Tu apartado debe identificar:

- Fuente, periodo y conjunto analizado: mensajes, versiones distintas o eventos actuales.
- Código o consultas utilizados y resultados obtenidos.
- Acciones aplicadas y resultados antes/después cuando corresponda.
- Limitaciones y posibles mejoras.

**Ejemplo de tabla para incluir en la memoria o notebook**

Ejemplo ficticio de una muestra de **100 versiones recibidas**, antes de deduplicar:

| Comprobación | Resultado | Acción |
|---|---|---|
| Magnitud informada | 92/100 = 92 % | Conservar ocho nulos; informar su exclusión en medias |
| Versiones distintas | 95/100 = 95 % | Identificar cinco repeticiones |
| Coordenadas válidas | 98/100 = 98 % | Poner dos registros en cuarentena |

Estos porcentajes tienen el mismo denominador, pero los problemas pueden solaparse: no sumes 8 + 5 + 2 para concluir cuántos registros «malos» hay.

Completa además consistencia, actualidad y exactitud. Para actualidad, mide la diferencia entre recepción y tiempo del evento, aclarando que una revisión antigua puede aumentar esa diferencia. Para exactitud, explica que comprobar rangos no demuestra que la magnitud física sea correcta.

No inventes errores en los datos reales. Para probar tu código, crea casos artificiales separados y etiquetados.

Una explicación válida sería: «La completitud de magnitud es del 92 %. Conservamos los ocho nulos porque desconocido no significa magnitud cero. Los excluimos de la media de magnitud e indicamos el número de observaciones utilizadas».

No es obligatorio crear una tabla adicional de métricas o incidencias de calidad. Sí debes conservar los rechazos y sus motivos, por ejemplo en la tabla de cuarentena. Automatizar un informe con `generar_informe_calidad.py` o añadir un panel de calidad son opciones voluntarias, no requisitos para obtener sobresaliente.

### 18. ¿Para qué usamos el archivo de países si el mapa ya muestra las fronteras?

Tiene dos usos distintos:

- **En Python:** comprobar en qué polígono está un evento y añadir identificador de país, nombre, continente o subregión.
- **En Angular:** dibujar las fronteras con Leaflet.

Mostrar fronteras no asigna automáticamente un país en la base de datos. Esa integración debe hacerla el backend.

### 19. ¿Cómo asigno un país? ¿Y si está en el océano?

Construye un punto con **longitud y latitud** y comprueba qué polígono lo contiene, usando por ejemplo una biblioteca geoespacial. Usa el mismo sistema de coordenadas en puntos y polígonos.

Ejemplo conceptual: el punto `(-3.7, 40.4)` está dentro del polígono de España en el catálogo; el registro preparado recibe `country_id = "ESP"`.

Un punto del Atlántico puede no pertenecer a ningún polígono. Guarda país nulo y muéstralo como «Sin país asignado». No lo atribuyas al país más cercano.

Los límites son simplificados. Documenta cómo resuelves puntos sobre fronteras, varias coincidencias o falta de cobertura; no afirmes precisión cartográfica que el catálogo no tiene.

### 20. ¿Cómo puede ser el modelo de datos?

Esta es una orientación, no un SQL completo para copiar:

| Tabla | Una fila representa | Clave o restricción importante |
|---|---|---|
| `pais` | Una entidad del catálogo | `country_id` único |
| `fecha` | Un día UTC | `fecha_id` único |
| `evento_actual` | La versión más reciente de un terremoto | `event_id` único |
| `evento_version` | Una versión observada | `(event_id, updated)` único |
| `cuarentena` | Un registro rechazado y su motivo | Referencia al mensaje/original |

La tabla de hechos `evento_actual` puede contener magnitud, profundidad y claves a país y fecha. País puede ser nulo. Los timestamps completos deben conservarse para calcular ventanas horarias.

Justifica índices en función de las consultas. Por ejemplo, un índice temporal puede ayudar al filtro por intervalo. No afirmes que un índice acelera todo: mide una consulta relevante antes y después.

## F. Histórico, ventanas y conclusiones

### 21. ¿Tengo que descargar un año entero cada minuto?

No. Son trabajos distintos:

| Trabajo | Frecuencia |
|---|---|
| Descarga del histórico de 2025 | Una carga inicial, dividida en intervalos |
| Consulta del feed reciente | Aproximadamente cada 60 segundos |
| Consulta de Angular a nuestra API | Aproximadamente cada 60 segundos |

Para la carga inicial, procesa los archivos con las mismas reglas de limpieza e integración. Puedes enviarlos por Kafka con un productor de carga inicial o reutilizar la lógica común mediante un proceso batch; documenta la elección. La reproducción de demostración sí debe circular por Kafka.

El histórico no debe perderse al reiniciar los contenedores. Utiliza volúmenes y un procedimiento reproducible de carga.

### 22. ¿Qué es una ventana fija de una hora? Ponme un ejemplo.

Agrupa por la hora de **ocurrencia**, no por la hora a la que llegó el mensaje:

| Evento | Hora de ocurrencia UTC | Ventana |
|---|---|---|
| A | 10:03 | [10:00, 11:00) |
| B | 10:48 | [10:00, 11:00) |
| C | 11:00 | [11:00, 12:00) |

Resultado: la primera ventana contiene dos terremotos y la segunda uno. El símbolo `)` indica que el extremo final no se incluye.

Si B llega a las 11:05, sigue perteneciendo a la ventana de las 10:00. Si llega una revisión de B, no se suma otro terremoto. Si cambia su tiempo de ocurrencia, deben corregirse las ventanas afectadas.

Una opción sencilla para esta práctica es calcular las agregaciones consultando `evento_actual` con SQL. Así las revisiones se reflejan sin mantener contadores incrementales complejos.

### 23. ¿Qué hago exactamente en la comparación histórica?

Compara cantidades del mismo tipo y con filtros equivalentes.

Ejemplo ficticio: durante 2025 hubo **3.650 eventos** de magnitud ≥4 en el ámbito elegido. Como 2025 tiene 365 días, la media fue **10 eventos por día**, incluyendo los días con cero eventos.

En las últimas 24 horas aparecen **14 eventos** con el mismo ámbito, tipo y filtro de magnitud.

```text
Media diaria histórica = 3.650 / 365 = 10
Diferencia = 14 − 10 = 4 eventos
Variación respecto a la media = (14 − 10) / 10 × 100 = 40 %
```

Conclusión válida: «El recuento observado es un 40 % superior a esa media histórica, bajo estos filtros».

No permite concluir que vaya a ocurrir un gran terremoto. El periodo reciente puede recibir eventos tardíos. Si la media histórica es cero, la variación porcentual no está definida: muestra ND y explica el caso.

No compares todos los eventos recientes con un histórico filtrado a magnitud ≥4. Aplica también ese filtro al periodo reciente.

### 24. ¿Qué significa entregar tres conclusiones? ¿Sirven tres gráficos?

Un gráfico presenta datos; una conclusión interpreta un resultado con su contexto.

Ejemplos ficticios:

1. «De 20 eventos del periodo seleccionado, 12 tienen profundidad inferior a 70 km: el 60 %, sin valores nulos en este campo».
2. «Cinco de esos 20 eventos no tienen país asignado; se han conservado y se muestran por separado».
3. «Con magnitud ≥4 y el mismo ámbito geográfico, el recuento reciente es 14 frente a una media histórica diaria de 10».

Indica siempre fecha, ámbito, filtros y denominador. «Hay muchos terremotos» no es una conclusión fundamentada.

## G. API, mapa y publicación

### 25. ¿Angular puede llamar directamente a USGS para simplificar?

Para explorar la fuente, sí. **En la entrega, el panel debe consultar vuestra API y representar los datos procesados por vuestro sistema.** De otro modo no demostraríais que Kafka, el consumidor y la base alimentan el panel.

Consulta `CONTRATO-API.md`. El mapa entregado espera `GET /api/eventos` con un `FeatureCollection`. Para añadir los filtros, utiliza el contrato y adapta los controles de Angular.

Ejemplo de consulta por intervalo:

```text
GET /api/eventos?start=2026-10-27T10:00:00Z&end=2026-10-27T11:00:00Z&min_mag=4
```

### 26. ¿Cómo cambio de los puntos ficticios a mis datos?

Edita `frontend/public/config.json`:

```json
{
  "mode": "api",
  "apiUrl": "https://TU-DOMINIO-NGROK",
  "refreshMs": 60000,
  "skipNgrokWarning": true
}
```

Sustituye el dominio por el real. No añadas `/api` al final: el componente ya añade `/api/eventos`. Recarga la página; si está publicada, recompila y despliega la configuración actualizada.

En modo `demo`, el mapa carga un archivo fijo: no se conecta al backend ni demuestra streaming.

### 27. ¿Tengo que calcular las posiciones en píxeles o buscar una imagen del mundo?

No. La base usa Leaflet: coloca los puntos a partir de coordenadas y dibuja el catálogo GeoJSON. El fondo se obtiene de OpenStreetMap.

GeoJSON utiliza `[longitud, latitud]`. Las llamadas manuales como `L.circleMarker` utilizan `[latitud, longitud]`. Intercambiarlas es una causa habitual de puntos mal situados.

El tamaño del círculo representa una escala visual de magnitud, no el área afectada. Conserva leyenda y atribución del mapa base.

### 28. ¿Por qué no se conecta un contenedor a `localhost`?

Porque `localhost` significa «este mismo contenedor», no «mi portátil» ni «el otro servicio».

Ejemplos si tus servicios se llaman `kafka`, `postgres` y `api`:

| Desde | Hacia | Dirección orientativa |
|---|---|---|
| Productor o consumidor | Kafka | `kafka:9092` si ese es el listener interno configurado |
| Consumidor o API | PostgreSQL | `postgres:5432` |
| ngrok en Docker | API | `http://api:8000` |
| ngrok instalado en el equipo | API publicada en el host | `http://localhost:8000` |

Los nombres y puertos deben coincidir con tu Compose. Kafka además anuncia direcciones a sus clientes: revisa `advertised.listeners` si conecta inicialmente pero luego falla.

### 29. ¿Necesito instalar un certificado para publicar la API por HTTPS?

No para la configuración de esta práctica. ngrok proporciona la dirección pública HTTPS y gestiona su certificado. La API puede recibir HTTP en la red Docker.

Si ngrok está instalado en el equipo y la API tiene el puerto publicado:

```bash
ngrok http 8000
```

Si el agente está en otro contenedor de la misma red:

```bash
ngrok http http://api:8000
```

FastAPI/Uvicorn debe escuchar en `0.0.0.0:8000` dentro del contenedor. No publiques Kafka o PostgreSQL mediante el túnel. Mantén el token de ngrok fuera de Git y del frontend.

### 30. ¿Qué es CORS y por qué aparece un error si la API funciona?

El navegador ve dos orígenes diferentes: la web de Netlify y la API de ngrok. El backend debe permitir el origen de esa web mediante CORS.

Que una URL funcione al abrirla directamente no demuestra que el navegador permita leerla desde otra página.

Autoriza el dominio exacto de Netlify, el origen de desarrollo cuando corresponda y la cabecera `ngrok-skip-browser-warning`. La petición `OPTIONS` previa puede ser normal. El middleware CORS debe responderla correctamente.

Si Angular recibe HTML en lugar de JSON, comprueba la URL y si aparece una página de aviso de ngrok. No utilices `mode: "no-cors"`: no permite a Angular leer una respuesta JSON opaca.

### 31. ¿Qué ocurre si cierro el portátil o paro el productor?

Son casos diferentes:

| Situación | Qué debería observarse |
|---|---|
| Se para el productor, pero la API sigue activa | La API responde, pero la última ingesta queda antigua |
| Se para el consumidor | Se acumulan mensajes en Kafka dentro de su retención |
| Se cierra ngrok | El panel no consigue consultar la API |
| Se apaga el equipo | El frontend de Netlify abre, pero el backend no está disponible |

Por eso necesitas distinguir **última consulta del panel**, **generación de la respuesta** y **última ingesta de USGS**. Una respuesta recién generada puede contener datos antiguos.

La entrega no exige disponibilidad 24/7. Sí exige un procedimiento para activar el sistema durante la defensa y mensajes claros de desconexión o desactualización.

## H. Demostración, evaluación y entrega

### 32. ¿Cómo demuestro actividad si no aparece un nuevo terremoto durante la defensa?

Reproduce una selección del histórico de forma acelerada. Por ejemplo, publica diez eventos ya guardados, uno cada dos segundos, conservando sus fechas originales y registrando la hora de reproducción.

Usa un topic y tablas/esquema separados de los datos live, o un aislamiento equivalente. Mostrar «REPRODUCCIÓN» es obligatorio para no confundirlo con actualidad.

**Importante:** si reproduces 2025 y la API filtra por defecto las últimas 24 horas de 2026, no verás los puntos. La vista de reproducción debe consultar el intervalo histórico correspondiente y los datos aislados de replay. No cambies las fechas originales solo para que aparezcan.

Añade duplicados y revisiones controladas para demostrar el comportamiento de la pregunta 12. El archivo demo del frontend es estático y no sustituye esta prueba del pipeline.

### 33. ¿Qué tengo que explicar sobre complejidad y costes?

Ejemplo de complejidad: buscar el último `updated` recorriendo una lista de N identificadores cuesta O(N) por búsqueda; un diccionario ofrece O(1) de media, a cambio de memoria. Explica qué parte de tu implementación utiliza esa estructura.

Mide al menos tres tamaños de entrada y registra tiempo y memoria. Identifica equipo, operación y procedimiento. Para estudiar un volumen mayor puedes generar datos sintéticos, pero no mezclarlos con el análisis de sismicidad real.

En costes, incluye tiempo de desarrollo, recursos del equipo, almacenamiento y mantenimiento. Ejemplo ficticio de electricidad: 0,05 kW adicionales × 4 h = 0,2 kWh; a 0,20 €/kWh serían 0,04 €. Son supuestos ilustrativos, no una medición de tu equipo ni un precio vigente. Explica cómo obtienes tus propios valores.

### 34. ¿Qué evidencias tengo que aportar para la rúbrica?

| Criterio | Ejemplo de evidencia que puedo mostrar |
|---|---|
| Extracción | Archivos descargados, consulta usada y tabla de tipos/unidades |
| Calidad | Apartado en memoria o notebook con código/consultas, porcentajes, problemas detectados y acciones |
| Modelado | Diagrama, claves, integración por país y prueba de revisión sin duplicar |
| Análisis | Resultados por ventanas, distribuciones, comparación y tres conclusiones |
| Reflexión | Mediciones, complejidad, costes, limitaciones y mejoras |

El enunciado contiene los niveles completos de evaluación. Esta tabla no añade porcentajes ni nuevos criterios.

### 35. ¿Qué compruebo antes de entregar?

- [ ] Los cinco servicios arrancan con Docker Compose siguiendo mis instrucciones.
- [ ] Uso datos reales y conservo su procedencia y originales.
- [ ] Repetir un mensaje no duplica los efectos; una revisión antigua no sustituye a una nueva.
- [ ] La base conserva los datos al reiniciar los servicios.
- [ ] Tengo registros sin país y nulos tratados de forma justificada.
- [ ] La API consulta PostgreSQL y Angular consulta esa API.
- [ ] Mapa, tabla y estadísticas utilizan filtros coherentes.
- [ ] La comparación histórica tiene los mismos filtros y periodos comparables.
- [ ] Puedo abrir el panel desde otro dispositivo con el túnel activo.
- [ ] Si falla la API, el panel lo indica y no presenta datos antiguos como recién obtenidos.
- [ ] La reproducción está aislada y se identifica como tal.
- [ ] Aporto el apartado de calidad en memoria o notebook, con código/consultas, resultados y decisiones; también el modelo, análisis, mediciones y costes.
- [ ] Puedo explicar un evento de principio a fin y una decisión de diseño propia.
- [ ] No he incluido credenciales ni `node_modules` en el repositorio.

## Guía rápida: si algo falla, empieza aquí

| Síntoma | Primera comprobación |
|---|---|
| No se ve ningún mapa | Instala dependencias, verifica CSS de Leaflet y altura del contenedor |
| Se ve el fondo pero no las fronteras | Comprueba la descarga local de `datos/paises.geojson` |
| Solo aparecen cuatro puntos ficticios | Comprueba si `config.json` sigue en modo demo |
| Los puntos aparecen en sitios extraños | Revisa el orden longitud/latitud |
| El productor no conecta con Kafka | Nombre del servicio, listener interno y salud del broker |
| El consumidor recibe, pero no guarda | Logs, conexión PostgreSQL, esquema y transacción |
| La API responde vacía | Datos en la tabla correcta, filtros y fechas del periodo |
| Angular dice error de JSON | ¿La URL devuelve JSON o una página HTML de error/aviso? |
| Funciona en el navegador directo, no desde Angular | CORS y preflight OPTIONS |
| Suben los recuentos cada minuto sin eventos nuevos | Duplicados, revisiones y contador basado en mensajes |
| El replay no muestra nada | Intervalo histórico, aislamiento y filtro de últimas 24 horas |

## Documentos de referencia

- `ENUNCIADO.md`: requisitos y rúbrica.
- `README.md`: instalación del mapa, conexión y despliegue.
- `CONTRATO-API.md`: estructura que espera Angular.
- `FUENTES-Y-LICENCIAS.md`: origen del catálogo y documentación de proveedores.
- `VALIDACION.md`: comprobaciones realizadas y límites del material inicial.
