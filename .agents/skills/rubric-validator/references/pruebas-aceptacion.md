# Las 11 Pruebas de Aceptación Obligatorias (Sección 11 del Enunciado)

Cada una de estas pruebas debe ser demostrable durante la defensa y verificada automáticamente con un script de prueba de aceptación (`scripts/probar_aceptacion.py`).

| # | Prueba de Aceptación | Escenario / Acción | Resultado Esperado | Criterio de Éxito Técnico |
|---|---|---|---|---|
| **P1** | **Recibir un evento nuevo** | Publicar a Kafka un sismo nunca antes visto | Una fila en `eventos`, visible en `/api/eventos`, mapa y KPI | `INSERT` en `eventos` con HTTP 200 en la API |
| **P2** | **Reenviar la misma versión** | Reenviar el mismo mensaje con idéntico `updated` | No aumenta el número de terremotos | Operación idempotente: recuento total inalterado |
| **P3** | **Recibir una versión posterior** | Enviar sismo existente con `updated` mayor y magnitud/lugar corregido | Cambian los datos actuales y las agregaciones afectadas | Actualiza `eventos` y añade fila en `eventos_versiones` |
| **P4** | **Recibir versión antigua desfasada** | Enviar sismo existente con `updated` menor al ya almacenado | No sustituye a la versión más reciente | Se ignora o audita sin sobrescribir el registro actual |
| **P5** | **Magnitud nula (`mag: null`)** | Terremoto instrumental sin magnitud calculada todavía | Se conserva con tratamiento documentado y se visualiza como ND | Almacena `NULL` en base de datos; API y frontend lo muestran como "ND" sin fallar |
| **P6** | **Coordenadas inválidas** | Sismo con latitud > 90 o longitud > 180 | Va a cuarentena con motivo; no se inventan puntos en el mapa | Inserción en `eventos_cuarentena`, no entra en `eventos` ni mapa |
| **P7** | **Evento marítimo (en océano)** | Sismo en medio del Océano Pacífico | Queda con `country_code: NULL` ("Sin país asignado"); se incluye en análisis global | Se dibuja en mapa y cuenta en estadísticas sin lanzar error de clave foránea |
| **P8** | **Reiniciar consumidor** | Matar contenedor del consumidor y volver a arrancarlo | Reanuda desde el último offset confirmado sin duplicar efectos ya persistidos | Tolerancia a fallos y reanudación limpia con commit manual de offset |
| **P9** | **Cerrar el túnel ngrok** | Detener el agente/túnel de ngrok | El panel Angular muestra aviso de desconexión y mantiene última lectura | UI muestra estado de error/alerta sin romper la aplicación SPA |
| **P10** | **Volver a abrir el túnel** | Reiniciar el túnel ngrok | Las consultas se recuperan automáticamente en el siguiente intervalo | El panel vuelve a verde/conectado en el refresco automático de 60s |
| **P11** | **Reproducción histórica (`replay`)** | Ejecutar script de replay histórico acelerado | Se procesa por Kafka con `mode: "replay"` sin alterar la pureza del feed en vivo | Eventos etiquetados claramente como `replay`, visibles en la interfaz |
