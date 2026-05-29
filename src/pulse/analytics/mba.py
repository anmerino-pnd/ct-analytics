"""
Market Basket Analysis (MBA) por segmento.

Aplica FP-Growth + association rules a los items de cada segmento para
detectar patrones de co-compra (qué se compra junto).

API pública:
    calcular_mba(df_items, df_segmentos, **params) -> dict[str, DataFrame]
        Calcula reglas de asociación por segmento.
        Retorna un dict con 3 DataFrames:
            "por_segmento" — todas las reglas estadísticamente significativas
            "exclusivas"   — reglas que aparecen en solo un segmento
            "accionables"  — subconjunto de 1→1 y 1→2 (vista por defecto del dashboard)

Decisiones de diseño (consistentes con notebook 05):
- Granularidad: familia (clave sin dígitos). La columna familia debe venir
  precomputada en df_items.
- Support absoluto + relativo combinados: max(min_support_count, min_support_pct * n).
  Protege contra micro-nichos en segmentos grandes y permite reglas en chicos.
- Dedup de reglas simétricas (A→B y B→A son una sola).
- Filtro 1→1 / 1→2 para la vista "accionable" del dashboard.
- Cálculo de ticket promedio solo para reglas accionables (top N por lift),
  para no inflar tiempos de cómputo.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
from mlxtend.frequent_patterns import association_rules, fpgrowth
from mlxtend.preprocessing import TransactionEncoder

log = logging.getLogger(__name__)


def calcular_mba(
    df_items: pd.DataFrame,
    df_segmentos: pd.DataFrame,
    df_orders: pd.DataFrame,
    min_support_count: int = 30,
    min_support_pct: float = 0.001,
    min_confidence: float = 0.20,
    min_lift: float = 3.0,
    top_n_accionables: int = 30,
    claves_a_ignorar: Optional[list[str]] = None,
) -> dict[str, pd.DataFrame]:
    """
    Calcula reglas MBA por segmento y retorna los 3 parquets del pipeline.

    Args:
        df_items: DataFrame con [order_id, cliente_id, clave, familia].
            La columna 'familia' debe venir precomputada.
        df_segmentos: DataFrame con [cliente_id, segmento_cluster].
            Generado por segmentar_clientes().
        df_orders: DataFrame con [order_id, pago_total]. Necesario para
            calcular ticket_medio y revenue_total de las reglas accionables.
        min_support_count: pedidos mínimos absolutos que respaldan una regla.
        min_support_pct: pedidos mínimos como % del segmento. Se usa el
            mayor de los dos umbrales (absoluto vs relativo).
        min_confidence: confianza mínima (0-1).
        min_lift: lift mínimo (3.0 = co-compra al menos 3x más probable que el azar).
        top_n_accionables: por segmento, cuántas reglas accionables enriquecemos
            con ticket_medio/revenue_total (es el cálculo más caro).
        claves_a_ignorar: claves que se excluyen ANTES del análisis (cargos por
            tarjeta, envíos, comisiones — cosas que no son productos para MBA).
            Default: ["CARGO100"]. Pasar [] para no filtrar nada.

    Returns:
        dict con tres DataFrames:
        - "por_segmento": todas las reglas (varios miles).
        - "exclusivas":   reglas que aparecen en solo un segmento.
        - "accionables":  reglas 1→1 y 1→2 con ticket_medio/revenue_total.
    """
    _validar_columnas(df_items, ["order_id", "clave", "cliente_id", "familia"])
    _validar_columnas(df_segmentos, ["cliente_id", "segmento_cluster"])
    _validar_columnas(df_orders, ["order_id", "pago_total"])

    # 0. Filtrar claves no-producto (cargos financieros, etc.) ANTES de cualquier cálculo.
    #    Esto es consistente con el notebook v3 de referencia.
    if claves_a_ignorar is None:
        claves_a_ignorar = ["CARGO100"]
    if claves_a_ignorar:
        n_antes = len(df_items)
        df_items = df_items[~df_items["clave"].isin(claves_a_ignorar)].copy()
        n_filtrados = n_antes - len(df_items)
        if n_filtrados > 0:
            log.info(
                "Filtradas %s líneas con claves no-producto %s",
                f"{n_filtrados:,}",
                claves_a_ignorar,
            )

    # 1. Preparar canastas: solo pedidos multi-familia, cruzados con segmento
    df_basket = _preparar_canastas(df_items, df_segmentos)

    # 2. Extraer reglas por segmento
    reglas_por_seg = {}
    segmentos = df_basket["segmento_cluster"].unique().tolist()

    for seg in segmentos:
        log.info("Procesando segmento '%s'", seg)
        df_seg = df_basket[df_basket["segmento_cluster"] == seg]
        reglas = _extraer_reglas_segmento(
            df_seg,
            min_support_count=min_support_count,
            min_support_pct=min_support_pct,
            min_confidence=min_confidence,
            min_lift=min_lift,
            segmento_nombre=seg,
        )
        reglas_por_seg[seg] = reglas
        log.info("  → %s reglas", f"{len(reglas):,}")

    # 3. Consolidar en un DataFrame único
    df_todas = pd.concat(
        [r for r in reglas_por_seg.values() if not r.empty],
        ignore_index=True,
    )

    if df_todas.empty:
        log.warning("Ningún segmento produjo reglas. Retornando DataFrames vacíos.")
        return _empty_result()

    log.info("Total reglas (todos los segmentos): %s", f"{len(df_todas):,}")

    # 4. Reglas exclusivas
    df_exclusivas = _identificar_exclusivas(df_todas)
    log.info("Reglas exclusivas: %s", f"{len(df_exclusivas):,}")

    # 5. Reglas accionables (1→1, 1→2) con valor monetario
    df_accionables = _calcular_accionables(
        df_todas, df_items, df_orders, top_n=top_n_accionables
    )
    log.info("Reglas accionables: %s", f"{len(df_accionables):,}")

    return {
        "por_segmento": df_todas,
        "exclusivas": df_exclusivas,
        "accionables": df_accionables,
    }


# ----------------------------------------------------------------
# Helpers internos
# ----------------------------------------------------------------
def _preparar_canastas(
    df_items: pd.DataFrame, df_segmentos: pd.DataFrame
) -> pd.DataFrame:
    """Filtra a pedidos multi-familia y cruza con segmento."""
    # Identificar pedidos con al menos 2 familias distintas
    fams_por_pedido = df_items.groupby("order_id")["familia"].nunique()
    pedidos_multi = fams_por_pedido[fams_por_pedido > 1].index

    df = df_items[df_items["order_id"].isin(pedidos_multi)].copy()

    # Cruzar con segmento
    df = df.merge(
        df_segmentos[["cliente_id", "segmento_cluster"]],
        on="cliente_id",
        how="inner",
    )

    log.info(
        "Canastas multi-familia: %s pedidos, %s líneas, %s segmentos",
        f"{len(pedidos_multi):,}",
        f"{len(df):,}",
        df["segmento_cluster"].nunique(),
    )
    return df


def _extraer_reglas_segmento(
    df_segmento: pd.DataFrame,
    min_support_count: int,
    min_support_pct: float,
    min_confidence: float,
    min_lift: float,
    segmento_nombre: str,
) -> pd.DataFrame:
    """Aplica FP-Growth y association_rules a las canastas de un segmento."""
    n_pedidos = df_segmento["order_id"].nunique()

    if n_pedidos < min_support_count * 2:
        log.warning(
            "  Segmento '%s' tiene solo %s pedidos multi-familia. Se omite.",
            segmento_nombre,
            f"{n_pedidos:,}",
        )
        return pd.DataFrame()

    # Umbral efectivo (el más exigente entre absoluto y relativo)
    support_count_efectivo = max(min_support_count, int(min_support_pct * n_pedidos))
    min_support = support_count_efectivo / n_pedidos

    log.info(
        "  Pedidos: %s | Umbral support: %s pedidos (%.4f%%)",
        f"{n_pedidos:,}",
        support_count_efectivo,
        min_support * 100,
    )

    # Matriz sparse
    basket_list = (
        df_segmento.groupby("order_id")["familia"].apply(list).tolist()
    )
    te = TransactionEncoder()
    te_ary = te.fit(basket_list).transform(basket_list, sparse=True)
    matrix = pd.DataFrame.sparse.from_spmatrix(te_ary, columns=te.columns_)

    # FP-Growth
    freq_items = fpgrowth(matrix, min_support=min_support, use_colnames=True)
    if freq_items.empty:
        return pd.DataFrame()

    # Reglas — manejo defensivo del parámetro num_itemsets (mlxtend ≥0.23)
    try:
        rules = association_rules(
            freq_items,
            metric="lift",
            min_threshold=min_lift,
            num_itemsets=len(freq_items),
        )
    except TypeError:
        rules = association_rules(freq_items, metric="lift", min_threshold=min_lift)

    if rules.empty:
        return pd.DataFrame()

    # Filtro adicional por confidence
    rules = rules[rules["confidence"] >= min_confidence].copy()
    if rules.empty:
        return pd.DataFrame()

    # Limpieza
    rules["antecedents"] = rules["antecedents"].apply(lambda x: ", ".join(sorted(x)))
    rules["consequents"] = rules["consequents"].apply(lambda x: ", ".join(sorted(x)))

    # Deduplicación simétrica (A→B y B→A)
    rules["par_id"] = rules.apply(
        lambda r: tuple(sorted([r["antecedents"], r["consequents"]])),
        axis=1,
    )
    rules = (
        rules.sort_values("confidence", ascending=False)
        .drop_duplicates("par_id")
        .drop(columns="par_id")
    )

    # Columnas auxiliares para filtrado
    rules["n_antecedents"] = rules["antecedents"].apply(lambda x: len(x.split(", ")))
    rules["n_consequents"] = rules["consequents"].apply(lambda x: len(x.split(", ")))
    rules["tamano_total"] = rules["n_antecedents"] + rules["n_consequents"]

    # Metadata del segmento
    rules["segmento"] = segmento_nombre
    rules["n_pedidos_segmento"] = n_pedidos
    rules["support_count"] = (rules["support"] * n_pedidos).round().astype(int)

    return rules.sort_values("lift", ascending=False).reset_index(drop=True)


def _identificar_exclusivas(df_todas: pd.DataFrame) -> pd.DataFrame:
    """
    Marca una regla como exclusiva si aparece en un único segmento.
    El identificador de regla es (antecedents, consequents).
    """
    df = df_todas.copy()
    df["regla_id"] = df["antecedents"] + " ⇒ " + df["consequents"]

    conteo_segs = df.groupby("regla_id")["segmento"].nunique()
    ids_exclusivos = conteo_segs[conteo_segs == 1].index

    df_excl = df[df["regla_id"].isin(ids_exclusivos)].drop(columns="regla_id")
    return df_excl.reset_index(drop=True)


def _calcular_accionables(
    df_todas: pd.DataFrame,
    df_items: pd.DataFrame,
    df_orders: pd.DataFrame,
    top_n: int = 30,
) -> pd.DataFrame:
    """
    Genera reglas accionables: 1→1 o 1→2, con ticket_medio y revenue_total
    calculados sobre los pedidos que las materializan.

    Por costo computacional, el cálculo de valor se hace solo sobre el top_n
    de reglas por lift de cada segmento.
    """
    # Filtro de tamaño
    df_acc = df_todas[
        (df_todas["n_antecedents"] == 1) & (df_todas["n_consequents"] <= 2)
    ].copy()

    if df_acc.empty:
        return pd.DataFrame()

    # Por segmento, quedarnos con top_n por lift
    df_acc = (
        df_acc.sort_values(["segmento", "lift"], ascending=[True, False])
        .groupby("segmento")
        .head(top_n)
        .reset_index(drop=True)
    )

    # Calcular ticket_medio y revenue_total para cada regla
    valores = df_acc.apply(
        lambda r: pd.Series(_calcular_valor_regla(
            r["antecedents"], r["consequents"], df_items, df_orders
        )),
        axis=1,
    )
    df_acc = pd.concat(
        [df_acc.reset_index(drop=True), valores.reset_index(drop=True)],
        axis=1,
    )

    return df_acc


def _calcular_valor_regla(
    antecedents: str,
    consequents: str,
    df_items: pd.DataFrame,
    df_orders: pd.DataFrame,
) -> dict:
    """
    Para una regla, encuentra los pedidos que la materializan (contienen TODAS
    las familias involucradas) y calcula su ticket promedio y revenue total.
    """
    familias = sorted(set(antecedents.split(", ") + consequents.split(", ")))

    df_f = df_items[df_items["familia"].isin(familias)]
    fam_por_pedido = df_f.groupby("order_id")["familia"].nunique()
    pedidos_validos = fam_por_pedido[fam_por_pedido == len(familias)].index

    if len(pedidos_validos) == 0:
        return {"ticket_medio": 0.0, "ticket_mediano": 0.0,
                "n_pedidos": 0, "revenue_total": 0.0}

    tickets = df_orders[df_orders["order_id"].isin(pedidos_validos)]["pago_total"]
    return {
        "ticket_medio": float(tickets.mean()),
        "ticket_mediano": float(tickets.median()),
        "n_pedidos": int(len(pedidos_validos)),
        "revenue_total": float(tickets.sum()),
    }


def _validar_columnas(df: pd.DataFrame, requeridas: list[str]) -> None:
    faltantes = [c for c in requeridas if c not in df.columns]
    if faltantes:
        raise ValueError(
            f"Faltan columnas requeridas: {faltantes}. "
            f"Disponibles: {df.columns.tolist()}"
        )


def _empty_result() -> dict[str, pd.DataFrame]:
    """DataFrames vacíos pero con el esquema correcto."""
    return {
        "por_segmento": pd.DataFrame(),
        "exclusivas": pd.DataFrame(),
        "accionables": pd.DataFrame(),
    }