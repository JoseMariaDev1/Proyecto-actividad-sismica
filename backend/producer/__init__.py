"""
Módulo del Productor de eventos sísmicos desde la API de USGS hacia Kafka.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.producer.producer import USGSProducer, main


def __getattr__(name: str):
    if name in ("USGSProducer", "main"):
        from backend.producer import producer
        return getattr(producer, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["USGSProducer", "main"]
