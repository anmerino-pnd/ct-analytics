"""
Runner del pipeline. Encadena los módulos en orden y persiste los outputs.

Tres modos de ejecución:
    daily   → ingest + segmentación + temporalidad. MBA bootstrap si no existe.
    weekly  → daily + recálculo de MBA.
    monthly → weekly + validación de drift (futuro: trigger de reentrenamiento).

Persiste 7 parquets en datos/processed/:
    - clientes_segmentados.parquet
    - mba_por_segmento.parquet
    - mba_exclusivas.parquet
    - mba_accionables.parquet
    - temp_hora_dia.parquet
    - temp_mensual.parquet
    - temp_bundles.parquet

Uso:
    from pulse.pipeline.runner import run
    resultado = run(modo="daily")
    print(resultado)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import pandas as pd

from pulse.analytics.familia import agregar_familia
from pulse.analytics.mba import calcular_mba
from pulse.analytics.segmentacion import segmentar_clientes
from pulse.analytics.temporalidad import calcular_temporalidad
from pulse.config.paths import PROCESSED
from pulse.etl.ingest import run_ingest
from pulse.pipeline.validacion import (
    QualityCheckFailed,
    validar_clientes_segmentados,
    validar_distribucion_segmentos,
    validar_ingest,
    validar_temporalidad_mensual,
)

log = logging.getLogger(__name__)

# Outputs del pipeline (contrato con el dashboard)
CLIENTES_OUT = PROCESSED / "clientes_segmentados.parquet"
MBA_POR_SEGMENTO = PROCESSED / "mba_por_segmento.parquet"
MBA_EXCLUSIVAS = PROCESSED / "mba_exclusivas.parquet"
MBA_ACCIONABLES = PROCESSED / "mba_accionables.parquet"
TEMP_HORA_DIA = PROCESSED / "temp_hora_dia.parquet"
TEMP_MENSUAL = PROCESSED / "temp_mensual.parquet"
TEMP_BUNDLES = PROCESSED / "temp_bundles.parquet"

# Inputs
ORDERS_HIST = PROCESSED / "orders_historicos.parquet"
ITEMS_HIST = PROCESSED / "items_historicos.parquet"

Modo = Literal["daily", "weekly", "monthly"]


@dataclass
class PipelineResult:
    """Resumen de una corrida del pipeline."""
    modo: str
    inicio: datetime
    fin: Optional[datetime] = None
    duracion_seg: Optional[float] = None
    pasos_ejecutados: list[str] = field(default_factory=list)
    pasos_saltados: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def exitoso(self) -> bool:
        return self.error is None

    def __str__(self) -> str:
        status = "✅ OK" if self.exitoso else "❌ FALLO"
        lines = [
            f"{status} Pipeline · modo={self.modo} · duración={self.duracion_seg:.1f}s"
            if self.duracion_seg
            else f"{status} Pipeline · modo={self.modo}",
            f"   Pasos: {' → '.join(self.pasos_ejecutados)}",
        ]
        if self.pasos_saltados:
            lines.append(f"   Saltados: {', '.join(self.pasos_saltados)}")
        if self.error:
            lines.append(f"   Error: {self.error}")
        return "\n".join(lines)


# ----------------------------------------------------------------
# Entry point principal
# ----------------------------------------------------------------
def run(
    modo: Modo = "daily",
    fecha_ref: Optional[datetime] = None,
    skip_ingest: bool = False,
) -> PipelineResult:
    """
    Ejecuta el pipeline en el modo indicado.

    Args:
        modo: "daily", "weekly" o "monthly".
        fecha_ref: Fecha de referencia (default ahora UTC). Útil para pruebas.
        skip_ingest: Si True, salta el paso de ingest (útil para re-procesar
            data ya extraída sin re-consultar Mongo).

    Returns:
        PipelineResult con resumen de la corrida.
    """
    if modo not in ("daily", "weekly", "monthly"):
        raise ValueError(f"Modo inválido: {modo!r}. Opciones: daily, weekly, monthly.")

    if fecha_ref is None:
        fecha_ref = datetime.now(tz=timezone.utc)

    inicio = datetime.now(tz=timezone.utc)
    t0 = time.time()
    resultado = PipelineResult(modo=modo, inicio=inicio)

    log.info("=" * 60)
    log.info("🚀 Pipeline iniciado · modo=%s · fecha_ref=%s", modo, fecha_ref.isoformat())
    log.info("=" * 60)

    try:
        # ========================================================
        # 1. INGEST (todos los modos)
        # ========================================================
        if skip_ingest:
            log.info("⏭️  Saltando ingest (skip_ingest=True)")
            resultado.pasos_saltados.append("ingest")
        else:
            _paso_ingest(resultado)

        # ========================================================
        # 2. CARGAR datos crudos
        # ========================================================
        df_orders, df_items = _cargar_historicos()

        # ========================================================
        # 3. SEGMENTACIÓN (todos los modos)
        # ========================================================
        df_clientes = _paso_segmentacion(df_orders, fecha_ref, resultado)

        # ========================================================
        # 4. MBA — solo en weekly/monthly, o bootstrap si no existe
        # ========================================================
        df_mba_accionables = _paso_mba(
            df_items, df_clientes, df_orders, modo, resultado
        )

        # ========================================================
        # 5. TEMPORALIDAD (todos los modos)
        # ========================================================
        _paso_temporalidad(
            df_orders, df_clientes, df_items, df_mba_accionables, fecha_ref, resultado
        )

        # ========================================================
        # 6. MONTHLY: validación de drift contra snapshot
        # ========================================================
        if modo == "monthly":
            _paso_drift_check(df_clientes, resultado)

    except QualityCheckFailed as e:
        log.error("❌ Quality check falló: %s", e)
        resultado.error = f"QualityCheckFailed: {e}"
    except Exception as e:
        log.exception("❌ Error inesperado en el pipeline")
        resultado.error = f"{type(e).__name__}: {e}"

    resultado.fin = datetime.now(tz=timezone.utc)
    resultado.duracion_seg = time.time() - t0

    log.info("=" * 60)
    log.info(str(resultado))
    log.info("=" * 60)

    return resultado


# ----------------------------------------------------------------
# Pasos individuales
# ----------------------------------------------------------------
def _paso_ingest(resultado: PipelineResult) -> None:
    log.info("\n--- Paso 1: Ingest desde MongoDB ---")
    n_orders_pre = _contar_filas(ORDERS_HIST)

    ingest_result = run_ingest()
    log.info(str(ingest_result))

    validar_ingest(
        n_orders_post=ingest_result.n_orders_total,
        n_orders_pre=n_orders_pre,
    )

    # Asegurar columna familia post-ingest (idempotente)
    df_items = pd.read_parquet(ITEMS_HIST)
    df_items = agregar_familia(df_items)
    df_items.to_parquet(ITEMS_HIST, index=False)

    resultado.pasos_ejecutados.append("ingest")


def _cargar_historicos() -> tuple[pd.DataFrame, pd.DataFrame]:
    log.info("\n--- Cargando datos crudos ---")
    df_orders = pd.read_parquet(ORDERS_HIST)
    df_items = pd.read_parquet(ITEMS_HIST)
    log.info("Orders: %s | Items: %s (pre-filtro)",
             f"{len(df_orders):,}", f"{len(df_items):,}")

    # Sanity: items debe tener familia
    if "familia" not in df_items.columns:
        log.warning("items sin columna familia. Derivándola al vuelo.")
        df_items = agregar_familia(df_items)

    # Filtrar claves no-producto (cargos financieros, etc.).
    # Consistente con notebook v3 de referencia.
    claves_a_ignorar = ["CARGO100"]
    n_antes = len(df_items)
    df_items = df_items[~df_items["clave"].isin(claves_a_ignorar)].copy()
    n_filtrados = n_antes - len(df_items)
    if n_filtrados > 0:
        log.info(
            "Items filtrados (claves no-producto %s): %s líneas",
            claves_a_ignorar,
            f"{n_filtrados:,}",
        )

    return df_orders, df_items


def _paso_segmentacion(
    df_orders: pd.DataFrame,
    fecha_ref: datetime,
    resultado: PipelineResult,
) -> pd.DataFrame:
    log.info("\n--- Paso 2: Segmentación de clientes ---")
    df_clientes = segmentar_clientes(df_orders, fecha_ref=fecha_ref)

    validar_clientes_segmentados(df_clientes)
    validar_distribucion_segmentos(df_clientes)

    df_clientes.to_parquet(CLIENTES_OUT, index=False)
    log.info("✅ Guardado: %s (%s clientes)", CLIENTES_OUT.name, f"{len(df_clientes):,}")
    resultado.pasos_ejecutados.append("segmentacion")
    return df_clientes


def _paso_mba(
    df_items: pd.DataFrame,
    df_clientes: pd.DataFrame,
    df_orders: pd.DataFrame,
    modo: str,
    resultado: PipelineResult,
) -> pd.DataFrame:
    """
    Decide si correr MBA o reutilizar parquets existentes.

    - weekly/monthly: siempre recalcula.
    - daily con MBA existente: reutiliza.
    - daily sin MBA (bootstrap): calcula esta vez.
    """
    necesita_mba = (
        modo in ("weekly", "monthly")
        or not MBA_ACCIONABLES.exists()  # bootstrap
    )

    if not necesita_mba:
        log.info("\n--- Paso 3: MBA reutilizado (modo daily, parquets existen) ---")
        resultado.pasos_saltados.append("mba")
        return pd.read_parquet(MBA_ACCIONABLES)

    razon = "bootstrap" if not MBA_ACCIONABLES.exists() else "recálculo periódico"
    log.info("\n--- Paso 3: MBA (%s) ---", razon)

    reglas = calcular_mba(df_items, df_clientes, df_orders)

    reglas["por_segmento"].to_parquet(MBA_POR_SEGMENTO, index=False)
    reglas["exclusivas"].to_parquet(MBA_EXCLUSIVAS, index=False)
    reglas["accionables"].to_parquet(MBA_ACCIONABLES, index=False)
    log.info(
        "✅ MBA guardado: %s reglas totales, %s exclusivas, %s accionables",
        f"{len(reglas['por_segmento']):,}",
        f"{len(reglas['exclusivas']):,}",
        f"{len(reglas['accionables']):,}",
    )
    resultado.pasos_ejecutados.append("mba")
    return reglas["accionables"]


def _paso_temporalidad(
    df_orders: pd.DataFrame,
    df_clientes: pd.DataFrame,
    df_items: pd.DataFrame,
    df_accionables: pd.DataFrame,
    fecha_ref: datetime,
    resultado: PipelineResult,
) -> None:
    log.info("\n--- Paso 4: Temporalidad ---")
    agregados = calcular_temporalidad(
        df_orders, df_clientes, df_items, df_accionables, fecha_ref=fecha_ref
    )

    validar_temporalidad_mensual(agregados["mensual"], df_clientes)

    agregados["hora_dia"].to_parquet(TEMP_HORA_DIA, index=False)
    agregados["mensual"].to_parquet(TEMP_MENSUAL, index=False)
    agregados["bundles"].to_parquet(TEMP_BUNDLES, index=False)
    log.info(
        "✅ Temporalidad guardada: %s/%s/%s filas",
        f"{len(agregados['hora_dia']):,}",
        f"{len(agregados['mensual']):,}",
        f"{len(agregados['bundles']):,}",
    )
    resultado.pasos_ejecutados.append("temporalidad")


def _paso_drift_check(
    df_clientes: pd.DataFrame,
    resultado: PipelineResult,
) -> None:
    """
    En modo monthly, compara la segmentación actual contra el snapshot histórico
    para detectar drift. Por ahora solo loggea; no toma acción automática.
    """
    log.info("\n--- Paso 5: Drift check (monthly) ---")
    snapshot_path = PROCESSED / "modelo_snapshot_v1.parquet"
    if not snapshot_path.exists():
        log.warning("No existe %s. Saltando drift check.", snapshot_path.name)
        resultado.pasos_saltados.append("drift_check")
        return

    snapshot = pd.read_parquet(snapshot_path)
    merged = df_clientes[["cliente_id", "segmento_cluster"]].merge(
        snapshot[["cliente_id", "segmento_cluster"]],
        on="cliente_id",
        suffixes=("_actual", "_snapshot"),
    )
    if merged.empty:
        log.warning("Sin clientes comunes entre actual y snapshot. Saltando drift.")
        resultado.pasos_saltados.append("drift_check")
        return

    coincidencia = (
        merged["segmento_cluster_actual"] == merged["segmento_cluster_snapshot"]
    ).mean()
    log.info(
        "Coincidencia con snapshot: %.1f%% (%s clientes comunes)",
        coincidencia * 100,
        f"{len(merged):,}",
    )

    if coincidencia < 0.6:
        log.warning(
            "⚠️  Drift fuerte detectado (coincidencia %.1f%% < 60%%). "
            "Considera reentrenar el modelo como v2.",
            coincidencia * 100,
        )

    resultado.pasos_ejecutados.append("drift_check")


def _contar_filas(path: Path) -> Optional[int]:
    """Cuenta filas de un parquet sin cargarlo. None si no existe."""
    if not path.exists():
        return None
    import pyarrow.parquet as pq
    return pq.ParquetFile(path).metadata.num_rows