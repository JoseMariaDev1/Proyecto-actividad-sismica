# Material del observatorio sísmico

Empieza por `ENUNCIADO.md`. Para una explicación paso a paso, consulta `FAQ-ALUMNADO.md`: contiene preguntas frecuentes, ejemplos de revisiones y duplicados y un itinerario de trabajo. Este paquete aporta el enunciado y la base cartográfica, no una solución completa del proyecto.

## 1. Ejecutar el mapa de demostración

Requisitos: Node.js 22.12 o posterior dentro de la rama 22, o Node 24; npm; acceso a Internet para instalar dependencias y descargar el mapa base.

```bash
cd frontend
npm ci
npm start
```

Abre http://localhost:4200 . Verás fronteras reales de países y **cuatro eventos ficticios**. Comprueba zoom, desplazamiento, selector de capas y fichas al pulsar. Si OpenStreetMap no responde, desactiva esa capa: las fronteras y puntos incluidos siguen siendo locales.

Se fija Angular 20.3, ngx-leaflet 20.0 y Leaflet 1.9.4 como combinación reproducible; no se pretende elegir las últimas versiones. Para un proyecto Angular existente, selecciona la versión de ngx-leaflet compatible con tu Angular en su changelog. No copies este package.json sobre un proyecto ajeno.

## 2. Qué archivos dibujan el mapa

| Archivo | Función |
|---|---|
| `src/app/app.component.ts` | Inicializa capas, carga GeoJSON y actualiza los puntos |
| `src/app/app.component.html` | Contenedor del mapa, estado y leyenda |
| `src/app/app.component.css` | Tamaño y presentación del mapa |
| `src/styles.css` | Estilos globales |
| `public/datos/paises.geojson` | Catálogo completo entregado, sin modificación |
| `public/datos/terremotos-demo.geojson` | Muestra sintética inicial |
| `public/config.json` | Modo demo o API y URL del backend |
| `angular.json` | Carga también el CSS de Leaflet y copia public al build |

`L.geoJSON()` interpreta Polygon/MultiPolygon y el orden de coordenadas automáticamente. Para crear un círculo manualmente se utiliza `[latitud, longitud]`. Las fronteras se dibujan sin relleno sobre OpenStreetMap. Se utiliza la proyección predeterminada del mapa base (Web Mercator): no superpongas un mapamundi equirectangular como si fuera compatible sin reproyectarlo. El catálogo ya contiene la representación cartográfica; no es necesario dibujar sobre una imagen JPG.

El componente sustituye la capa de eventos en cada respuesta: no acumula una copia por refresco. El backend sigue siendo responsable de servir una sola versión actual por evento. Se usan nodos DOM con texto para las fichas, evitando interpretar descripciones como HTML.

## 3. Conectar la API

El backend completo debe ejecutarse en Docker: productor Python, consumidor Python, Kafka, PostgreSQL y API FastAPI, como cinco servicios de Compose. El alumnado debe crear sus Dockerfile(s) y `compose.yaml`; este paquete aporta la base del frontend, no un backend implementado.

Una vez implementados esos archivos, arranca los servicios:

```bash
docker compose up --build -d
```

Usa nombres de servicio entre contenedores (por ejemplo `kafka`, `postgres` y `api`), configura salud/reintentos y conserva los datos en volúmenes. La API debe escuchar en `0.0.0.0:8000` dentro del contenedor y respetar `CONTRATO-API.md`.

**Opción A: ngrok instalado en el equipo.** Publica el puerto de la API con `127.0.0.1:8000:8000`. Configura ngrok en tu cuenta y ejecuta:

```bash
ngrok http 8000
```

**Opción B: ngrok en otro contenedor de la misma red Compose.** El comando del agente apuntará al nombre del servicio:

```bash
ngrok http http://api:8000
```

No uses `localhost:8000` desde el contenedor de ngrok: apuntaría al propio contenedor. Para esta opción no es necesario publicar el puerto de la API en el host. Proporciona el authtoken al agente mediante una variable de entorno o secreto, nunca en el frontend ni en Git.

**HTTPS sin certificados en FastAPI.** La dirección pública es HTTPS y ngrok proporciona y renueva el certificado. La conexión con el agente también está cifrada; el agente puede comunicarse con la API por HTTP dentro del equipo o de la red Docker. No hace falta configurar certificados en Uvicorn ni añadir un proxy TLS para esta práctica. El plan gratuito tiene cuotas de uso.

Cambia `frontend/public/config.json`:

```json
{
  "mode": "api",
  "apiUrl": "https://TU-DOMINIO-ASIGNADO",
  "refreshMs": 60000,
  "skipNgrokWarning": true
}
```

`apiUrl` no termina en `/api`: el componente añade `/api/eventos`. Usa el dominio asignado realmente a tu cuenta. Recarga la página después de cambiar la configuración. Configura CORS en el backend. Una llamada OPTIONS puede preceder al GET por la cabecera de ngrok; no la bloquees.

La consulta se programa después de terminar la anterior, evitando peticiones solapadas. El timeout es de 15 segundos. Si falla, se conserva la capa anterior y se muestra un aviso. Al destruir el componente se cancela la petición y el temporizador. La interfaz inicial muestra cuándo se leyó y generó la respuesta; añade la última ingesta real de USGS para detectar un productor parado.

## 4. Publicar en Netlify

1. Sube el proyecto a tu repositorio sin node_modules ni secretos.
2. Conecta el repositorio a Netlify.
3. Si el repositorio contiene todo el paquete, establece **Base directory: frontend**. Si subes solo frontend como raíz, deja la base vacía.
4. Comando de build: `npm run build`. Carpeta publicada relativa a esa base: `dist/observatorio/browser`.
5. El `netlify.toml` incluido contiene esos valores; `_redirects` permite recargar rutas SPA.
6. Ajusta CORS al dominio de Netlify. Verifica la web desde otro dispositivo.

No requiere SSR. Si integras el componente en una aplicación SSR existente, carga Leaflet solo en navegador; el ejemplo entregado es exclusivamente SPA.

`config.json` se copia al build: cuando cambies el dominio del backend, publica una nueva versión o actualiza el archivo servido por tu procedimiento de despliegue. No guardes claves en ese archivo público.

## 5. Lo que debes desarrollar

Productor, consumidor, almacenamiento, API, integración espacial, agregaciones, filtros y gráficas. El mapa se entrega para que el trabajo se centre en los datos. La clasificación por país que aparece en el popup la entrega el backend; dibujar fronteras no calcula automáticamente esa clasificación.

En `ENUNCIADO.md` tienes las pruebas y la rúbrica. En `FUENTES-Y-LICENCIAS.md`, procedencia y condiciones. En `VALIDACION.md`, las comprobaciones realizadas sobre el material base.

## 6. Cómo documentar la calidad, sin añadir una aplicación de informes

Incluye un apartado en la memoria o un notebook con tus comprobaciones, resultados y decisiones. Puedes ejecutar consultas SQL sobre PostgreSQL o código Python sobre los datos originales y preparados; no necesitas desarrollar un generador de informes.

Ejemplo: muestra la consulta/código que cuenta magnitudes nulas, su resultado y el porcentaje; explica por qué conservas los nulos y cómo los tratas al calcular medias. Haz lo mismo con duplicados, anomalías y las demás dimensiones que analices. Indica el conjunto de datos, periodo y denominador utilizado y compara antes/después cuando corresponda.

El consumidor valida, transforma y persiste datos; además conserva los rechazos y sus motivos. El alumnado prepara el apartado de calidad a partir de esas evidencias. **No es obligatorio crear `generar_informe_calidad.py`, una tabla específica de métricas/incidencias de calidad ni un panel de calidad en Angular.** El registro duradero de cuarentena solicitado en el enunciado sí debe conservarse, mediante una tabla o una solución equivalente documentada.

Generar automáticamente un Markdown/HTML de calidad o mostrar esas métricas en la web son ampliaciones opcionales. No añaden por sí mismas puntos ni son necesarias para el nivel máximo: se evalúan la calidad del análisis y las acciones justificadas.
