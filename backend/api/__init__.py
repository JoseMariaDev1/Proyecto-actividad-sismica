"""
Paquete API REST para el Observatorio de Actividad Sísmica.

Proporciona endpoints FastAPI conformes al CONTRATO-API.md para:
- Monitorización de salud y conectividad (/api/salud).
- Consulta de eventos sísmicos en formato GeoJSON FeatureCollection (/api/eventos).
- Agregaciones analíticas y distribuciones sismológicas (/api/estadisticas).
- Catálogo geográfico de países (/api/paises).
"""

from backend.api.main import app

__all__ = ["app"]
