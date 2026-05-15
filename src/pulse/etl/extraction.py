"""
Módulo de extracción de datos desde MongoDB.
Extrae pedidos de productos físicos de tipo CTonline para análisis.
"""

from datetime import datetime
from pymongo import MongoClient
from pulse.config.settings import mongo_uri, mongo_db, mongo_collection_pedidos

# Estatus que representan una venta concretada de producto físico
ESTATUS_CANCELADO = [
    "Cancelado", "FacturadoCancelado", "NONCancelado", 
    "NONFacturaESDActualizada", "NONFacturado", "NonCancelado", 
    "Rechazado", "_FacturaESDActualizada_cancelada", "_Facturado_cancelado"
]

def get_collection():
    """Retorna la colección de pedidos."""
    client = MongoClient(mongo_uri)
    db = client[mongo_db]
    return db[mongo_collection_pedidos]


def _build_status_filter(estatus_list: list[str]) -> dict:
    return {
        "$nor": [{f"estatus.{s}": {"$exists": True}} for s in estatus_list],
    }

def extract_pedidos_vendidos(
    fecha_inicio: str = "2024-01-01",
    fecha_fin: str = "2024-12-31",
    batch_size: int = 5000,
):
    """Yields documentos en batches — no materializa todo en memoria."""
    collection = get_collection()

    inicio = datetime.fromisoformat(f"{fecha_inicio}T00:00:00+00:00")
    fin    = datetime.fromisoformat(f"{fecha_fin}T23:59:59+00:00")

    query = {
        **_build_status_filter(ESTATUS_CANCELADO),
        "pedido.tipo": "CTonline",
        "pedido.fecha": {"$gte": inicio, "$lte": fin},
        "estatus.Facturado": {"$exists": True},
    }

    projection = {
        "_id": 1,
        "pedido.fecha": 1,
        "pedido.encabezado.cliente": 1,
        "pedido.encabezado.nombre": 1,
        "pedido.encabezado.pago": 1,
        "pedido.encabezado.tipodecambio": 1,
        "pedido.encabezado.iva": 1,
        "pedido.encabezado.plazo": 1,
        "pedido.encabezado.tipoPago": 1,
        "pedido.detalle.producto": 1,
    }

    cursor = (
        collection.find(query, projection)
        .batch_size(batch_size)
    )

    yield from cursor

def quick_sample(n: int = 5) -> list[dict]:
    """Muestra rápida para inspeccionar estructura."""
    collection = get_collection()

    query = {
        **_build_status_filter(ESTATUS_CANCELADO),
        "pedido.tipo": "CTonline",
    }

    return list(collection.find(query).limit(n))