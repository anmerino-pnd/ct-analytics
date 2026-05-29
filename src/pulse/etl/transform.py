"""
Módulo de transformación de datos.
Aplana documentos nested de MongoDB en DataFrames tabulares.
Soporta tanto iterables (generators/cursors) como listas.
"""

from __future__ import annotations
from typing import Iterable
import pandas as pd


def build_both_dfs(
    documentos: Iterable[dict],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Construye df_orders y df_items en una sola pasada.
    Acepta cualquier iterable: list, generator, cursor de pymongo.
    """
    order_rows: list[dict] = []
    item_rows:  list[dict] = []

    for doc in documentos:
        pedido     = doc.get("pedido", {})
        encabezado = pedido.get("encabezado", {})
        detalle    = pedido.get("detalle", {})
        productos  = detalle.get("producto", [])
        errores    = doc.get("errores", [])

        order_id   = str(doc["_id"])
        cliente_id = encabezado.get("cliente")
        fecha      = pedido.get("fecha")
        productos_validos = [
            p for p in productos
            if p.get("clave") is not None and p.get("clave") != "CARGO100"
        ]
        order_rows.append({
            "order_id":       order_id,
            "cliente_id":     cliente_id,
            "nombre_cliente": encabezado.get("nombre"),
            "fecha":          fecha,
            "pago_total":     encabezado.get("pago"),
            "iva_aplicado":   encabezado.get("iva"),
            "plazo":          encabezado.get("plazo"),
            "tipo_pago":      encabezado.get("tipoPago"),
            "num_productos":  len(productos_validos),  # ← antes: len(productos)
            "tiene_errores":  len(errores) > 0,
        })

        # — items (una fila por producto) —
        valor_dolar = encabezado.get("tipodecambio")
        for prod in productos:
            item_rows.append({
                "order_id":      order_id,
                "cliente_id":    cliente_id,
                "fecha":         fecha,
                "clave":         prod.get("clave"),
                "cantidad":      prod.get("cantidad"),
                "precio_final":  prod.get("precioFinal"),
                "moneda":        prod.get("moneda"),
                "valor_dolar":   valor_dolar,
                "promocion_id":  prod.get("promocion_id"),
                "promocion_tipo": prod.get("promocion_tipo"),
            })

    df_orders = _cast_orders(pd.DataFrame(order_rows))
    df_items  = _cast_items(pd.DataFrame(item_rows))
    return df_orders, df_items


def _cast_orders(df: pd.DataFrame) -> pd.DataFrame:
    df["fecha"]      = pd.to_datetime(df["fecha"], utc=True)
    df["pago_total"] = pd.to_numeric(df["pago_total"], errors="coerce")
    df["iva_aplicado"] = pd.to_numeric(df["iva_aplicado"], errors="coerce")
    return df


def _cast_items(df: pd.DataFrame) -> pd.DataFrame:
    df["fecha"]        = pd.to_datetime(df["fecha"], utc=True)
    df["cantidad"]     = pd.to_numeric(df["cantidad"],    errors="coerce")
    df["precio_final"] = pd.to_numeric(df["precio_final"], errors="coerce")
    df["valor_dolar"]  = pd.to_numeric(df["valor_dolar"],  errors="coerce")
    df["promocion_id"] = pd.to_numeric(df["promocion_id"], errors="coerce").astype("Int64")
    df["promocion_tipo"] = pd.to_numeric(df["promocion_tipo"], errors="coerce").astype("Int64")
    return df


def enrich_items(df_items: pd.DataFrame) -> pd.DataFrame:
    """Enriquece items con métricas monetarias homogéneas en MXN."""
    items = df_items.copy()
    items["precio_mxn"] = items["precio_final"]
    mask_usd = items["moneda"].eq("USD")
    items.loc[mask_usd, "precio_mxn"] = (
        items.loc[mask_usd, "precio_final"] * items.loc[mask_usd, "valor_dolar"]
    )
    items["subtotal_mxn"] = items["precio_mxn"] * items["cantidad"]
    return items