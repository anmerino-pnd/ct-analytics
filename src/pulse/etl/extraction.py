"""
Módulo de extracción de datos desde MongoDB.
Extrae pedidos de productos físicos de tipo CTonline para análisis.
"""

from datetime import datetime
from pymongo import MongoClient
from pulse.config.settings import mongo_uri, mongo_db, mongo_collection_pedidos

# Estatus que representan una venta concretada de producto físico
ESTATUS_VENTA = ["Surtido", "Facturado", "Terminado", "Enviado", "Transito"]


def get_collection():
    """Retorna la colección de pedidos."""
    client = MongoClient(mongo_uri)
    db = client[mongo_db]
    return db[mongo_collection_pedidos]


def _build_status_filter(estatus_list: list[str]) -> dict:
    """
    Construye el filtro OR para múltiples estatus.
    Verifica que al menos uno de los estatus exista en el documento
    Y que NO sea ESD (FacturaESDActualizada / Entregado).
    """
    return {
        "$or": [{f"estatus.{s}": {"$exists": True}} for s in estatus_list],
        "estatus.FacturaESDActualizada": {"$exists": False},
        "estatus.Entregado": {"$exists": False},
    }


def extract_pedidos(
    fecha_inicio: str = "2025-01-01",
    fecha_fin: str = "2025-12-31",
    batch_size: int = 5000,
) -> list[dict]:
    """
    Extrae pedidos de productos físicos vendidos en CTonline
    dentro de un rango de fechas.

    Incluye estatus: Surtido, Facturado, Terminado, Enviado, Transito.
    Excluye ESD (FacturaESDActualizada, Entregado).
    """
    collection = get_collection()

    inicio = datetime.fromisoformat(f"{fecha_inicio}T00:00:00+00:00")
    fin = datetime.fromisoformat(f"{fecha_fin}T23:59:59+00:00")

    query = {
        **_build_status_filter(ESTATUS_VENTA),
        "pedido.tipo": "CTonline",
        "pedido.fecha": {
            "$gte": inicio,
            "$lte": fin,
        },
    }

    projection = {
        "_id": 1,
        "pedido.fecha": 1,
        "pedido.encabezado.cliente": 1,
        "pedido.encabezado.nombre": 1,
        "pedido.encabezado.plazo": 1,
        "pedido.encabezado.tipoPago": 1,
        "pedido.detalle.producto": 1,
    }

    total = collection.count_documents(query)
    print(f"Pedidos físicos CTonline encontrados: {total:,}")

    cursor = collection.find(query, projection).batch_size(batch_size)
    documentos = list(cursor)

    print(f"Documentos extraídos: {len(documentos):,}")
    return documentos

def extract_pedidos_vendidos(
    fecha_inicio: str = "2024-01-01",
    fecha_fin: str = "2024-12-31",
    batch_size: int = 5000,
) -> list[dict]:
    """
    Extrae pedidos CTonline que representan ventas concretadas.
    Excluye: Cancelado, Rechazado.
    """
    collection = get_collection()

    inicio = datetime.fromisoformat(f"{fecha_inicio}T00:00:00+00:00")
    fin = datetime.fromisoformat(f"{fecha_fin}T23:59:59+00:00")

    query = {
        "pedido.tipo": "CTonline",
        "pedido.fecha": {"$gte": inicio, "$lte": fin},
        # Excluir pedidos que NO se concretaron o están en proceso
        "$nor": [
            {"estatus.Cancelado": {"$exists": True}},
            {"estatus.Rechazado": {"$exists": True}},
        ],
        # Al menos debe estar facturado (mínimo para considerar venta)
        "estatus.Facturado": {"$exists": True},
    }

    projection = {
        "_id": 1,
        "pedido.fecha": 1,
        "pedido.encabezado.cliente": 1,
        "pedido.encabezado.nombre": 1,
        "pedido.encabezado.plazo": 1,
        "pedido.encabezado.tipoPago": 1,
        "pedido.detalle.producto": 1,
    }

    total = collection.count_documents(query)
    print(f"Pedidos CTonline vendidos encontrados: {total:,}")

    cursor = collection.find(query, projection).batch_size(batch_size)
    documentos = list(cursor)

    print(f"Documentos extraídos: {len(documentos):,}")
    return documentos

def quick_sample(n: int = 5) -> list[dict]:
    """Muestra rápida para inspeccionar estructura."""
    collection = get_collection()

    query = {
        **_build_status_filter(ESTATUS_VENTA),
        "pedido.tipo": "CTonline",
    }

    return list(collection.find(query).limit(n))