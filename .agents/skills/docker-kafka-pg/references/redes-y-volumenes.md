# Referencia de Variables de Entorno y Redes en Docker Compose

## Tabla de Puertos y Exposición

| Servicio | Puerto Interno | Puerto Host (Local) | ¿Publicado en Internet? | Justificación |
|---|---|---|---|---|
| `postgres` | `5432` | `5432` | ❌ NO | Solo para inspección local con DBeaver/psql o tests locales |
| `kafka` | `9092` | `9092` | ❌ NO | Comunicación interna entre producer y consumer |
| `producer` | N/A | Ninguno | ❌ NO | Proceso batch/worker en segundo plano |
| `consumer` | N/A | Ninguno | ❌ NO | Proceso demonio de consumo de eventos |
| `api` | `8000` | `8000` | ⚠️ Solo vía túnel ngrok | Acceso por Angular desde Netlify y desarrollo local |

## Configuración de Redes (Networks)

Se define una red puente (*bridge network*) dedicada:
```yaml
networks:
  sismos-net:
    driver: bridge
```
Esto permite que los servicios se descubran mutuamente por su nombre de servicio (`postgres`, `kafka`, `api`) mediante el DNS interno de Docker.

## Volúmenes Persistentes

```yaml
volumes:
  postgres_data:
    driver: local
```
Los datos de la base de datos se almacenan en el host gestionados por Docker. Aunque se reinicien o actualicen los contenedores (`docker compose restart` o `docker compose up --build`), los sismos persistidos y el histórico se mantienen intactos.

