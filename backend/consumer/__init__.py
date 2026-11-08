"""
Paquete del Consumidor de Eventos Sísmicos.

Contiene el consumidor Kafka asíncrono, la validación de calidad de datos,
el enriquecimiento espacial con Shapely (Point-in-Polygon sobre Natural Earth)
y la persistencia transaccional e idempotente en PostgreSQL 16.
"""

from backend.consumer.spatial import SpatialMatcher

__all__ = ["SpatialMatcher"]
