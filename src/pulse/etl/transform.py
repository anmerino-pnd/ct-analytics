"""
Módulo de transformación de datos.
Aplana documentos nested de MongoDB en DataFrames tabulares.
"""

import pandas as pd


def build_orders_df(documentos: list[dict]) -> pd.DataFrame:
    """
    Construye DataFrame a nivel pedido (una fila por pedido).

    Columnas:
        order_id, cliente_id, nombre_cliente, fecha,
        plazo, tipo_pago, num_productos, tiene_errores
    """
    rows = []
    for doc in documentos:
        pedido = doc.get("pedido", {})
        encabezado = pedido.get("encabezado", {})
        detalle = pedido.get("detalle", {})
        productos = detalle.get("producto", [])
        errores = doc.get("errores", [])

        rows.append({
            "order_id": str(doc["_id"]),
            "cliente_id": encabezado.get("cliente"),
            "nombre_cliente": encabezado.get("nombre"),
            "fecha": pedido.get("fecha"),
            "plazo": encabezado.get("plazo"),
            "tipo_pago": encabezado.get("tipoPago"),
            "num_productos": len(productos),
            "tiene_errores": len(errores) > 0,
        })

    df = pd.DataFrame(rows)
    df["fecha"] = pd.to_datetime(df["fecha"], utc=True)
    return df


def build_items_df(documentos: list[dict]) -> pd.DataFrame:
    """
    Construye DataFrame a nivel producto (una fila por producto por pedido).
    Este es el insumo principal para Market Basket Analysis.

    Columnas:
        order_id, cliente_id, fecha, clave,
        cantidad, precio, precio_final, moneda
    """
    rows = []
    for doc in documentos:
        pedido = doc.get("pedido", {})
        encabezado = pedido.get("encabezado", {})
        detalle = pedido.get("detalle", {})
        productos = detalle.get("producto", [])
        order_id = str(doc["_id"])
        cliente_id = encabezado.get("cliente")
        fecha = pedido.get("fecha")

        for prod in productos:
            rows.append({
                "order_id": order_id,
                "cliente_id": cliente_id,
                "fecha": fecha,
                "clave": prod.get("clave"),
                "cantidad": prod.get("cantidad"),
                "precio": prod.get("precio"),
                "precio_final": prod.get("precioFinal"),
                "moneda": prod.get("moneda"),
            })

    df = pd.DataFrame(rows)
    df["fecha"] = pd.to_datetime(df["fecha"], utc=True)
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce")
    df["precio"] = pd.to_numeric(df["precio"], errors="coerce")
    df["precio_final"] = pd.to_numeric(df["precio_final"], errors="coerce")
    return df


def enrich_orders(df_orders: pd.DataFrame, df_items: pd.DataFrame) -> pd.DataFrame:
    """
    Enriquece df_orders con métricas calculadas desde df_items.
    Agrega: total_pedido, ticket_promedio por producto.
    """
    totales = (
        df_items
        .assign(subtotal=df_items["precio_final"] * df_items["cantidad"])
        .groupby("order_id")
        .agg(total_pedido=("subtotal", "sum"))
        .reset_index()
    )
    return df_orders.merge(totales, on="order_id", how="left")