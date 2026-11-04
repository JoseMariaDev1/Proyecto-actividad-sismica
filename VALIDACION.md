# Validación del material base

Comprobaciones realizadas el 27 de octubre de 2026:

- Instalación de las dependencias fijadas y generación de `package-lock.json`.
- `npm run build`: compilación de producción correcta, con TypeScript estricto y comprobación de plantillas Angular.
- Aviso de compilación: Leaflet 1.9.4 utiliza CommonJS; no impide generar el build.
- Catálogo JSON válido: 177 entidades, 177 códigos `ADM0_A3` distintos, geometrías Polygon/MultiPolygon.
- El build incluye config.json, el catálogo, la muestra y `_redirects`.
- Las muestras están etiquetadas como sintéticas, separadas del modo API.

Límites de esta comprobación:

- No se completó una prueba visual en navegador: el entorno no disponía de Chromium y no pudo descargar su ejecutable correctamente.
- No se ha desplegado una cuenta real de Netlify ni abierto un túnel ngrok del alumnado.
- La API y el pipeline son parte del trabajo a implementar, no servicios incluidos y probados en este paquete.

Antes de distribuir/defender, ejecutar la comprobación manual:

1. `npm ci` y `npm start` en frontend.
2. Verificar cuatro eventos ficticios y fronteras; abrir una ficha y el selector de capas.
3. Comprobar zoom, leyenda y atribución del mapa base.
4. Configurar vuestra API, confirmar la petición OPTIONS/GET y los datos recibidos.
5. Cerrar y reabrir el túnel; comprobar aviso y recuperación en el siguiente refresco.
6. Publicar en Netlify y repetir desde otro dispositivo.
