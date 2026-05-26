"""
pulse.modeling.segmentador
==========================

Wrapper para el modelo de segmentación de clientes basado en K-Means sobre features RFM.

Arquitectura interna: sklearn.Pipeline que encadena
    log1p (FunctionTransformer) → StandardScaler → KMeans

El log-transform vive dentro del pipeline. Esto significa que `predict()`
recibe RFM en escala ORIGINAL (recency en días, monetary en pesos, etc.)
y el pipeline aplica internamente las transformaciones necesarias.

Diseñado para:
- Reproducibilidad: ningún cliente debería cambiar de cluster entre corridas con los mismos datos.
- Seguridad de contrato: las features deben llegar en el orden exacto que el modelo espera.
- Versionado: cada modelo entrenado se identifica con un tag de versión.

Uso típico
----------
>>> from pulse.modeling.segmentador import SegmentadorClientes
>>> seg = SegmentadorClientes.load(version="v1")
>>> df_scoreado = seg.predict(df_rfm_nuevo)  # df_rfm_nuevo en escala original
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler


@dataclass
class ModelMetadata:
    """Metadata del modelo: qué features espera, cuándo se entrenó, qué nombres tienen los clusters."""

    version: str
    features: list[str]
    cluster_names: dict[int, str]
    trained_at: str
    n_clientes_entrenamiento: int
    silhouette_score: Optional[float] = None
    notas: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "features": self.features,
            "cluster_names": {str(k): v for k, v in self.cluster_names.items()},
            "trained_at": self.trained_at,
            "n_clientes_entrenamiento": self.n_clientes_entrenamiento,
            "silhouette_score": self.silhouette_score,
            "notas": self.notas,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ModelMetadata":
        return cls(
            version=d["version"],
            features=d["features"],
            cluster_names={int(k): v for k, v in d["cluster_names"].items()},
            trained_at=d["trained_at"],
            n_clientes_entrenamiento=d["n_clientes_entrenamiento"],
            silhouette_score=d.get("silhouette_score"),
            notas=d.get("notas"),
        )


def build_pipeline() -> Pipeline:
    """
    Construye el pipeline de segmentación.

    Pasos:
        1. log1p   — FunctionTransformer(np.log1p) para reducir el sesgo de
                     las distribuciones de RFM (monetary, frequency, etc).
                     Usa log(1+x) para tolerar ceros sin fallar.
        2. scaler  — StandardScaler para que todas las features tengan
                     media 0 y varianza 1.
        3. kmeans  — KMeans(k=5, random_state=42) para asignar segmentos.

    El pipeline se devuelve sin entrenar. Para entrenarlo:
        pipe = build_pipeline()
        pipe.fit(X)
    """
    return Pipeline([
        ("log1p", FunctionTransformer(np.log1p, validate=False)),
        ("scaler", StandardScaler()),
        ("kmeans", KMeans(n_clusters=5, random_state=42, n_init=10)),
    ])


class SegmentadorClientes:
    """
    Encapsula el pipeline completo de segmentación: log + scaler + kmeans + naming.

    Garantiza que las features lleguen en el orden esperado y que los clusters
    se conviertan a nombres de negocio antes de retornarse.

    Importante: `predict()` espera RFM en ESCALA ORIGINAL. El log-transform
    se aplica internamente. No transformes los datos antes de pasarlos.
    """

    def __init__(self, pipeline: Pipeline, metadata: ModelMetadata):
        self.pipeline = pipeline
        self.metadata = metadata

    # ----------------------------------------------------------------
    # Construcción desde un pipeline ya entrenado
    # ----------------------------------------------------------------
    @classmethod
    def from_fitted(
        cls,
        pipeline: Pipeline,
        version: str,
        features: list[str],
        cluster_names: dict[int, str],
        n_clientes_entrenamiento: int,
        silhouette_score: Optional[float] = None,
        notas: Optional[str] = None,
    ) -> "SegmentadorClientes":
        """Constructor conveniente cuando ya tienes un pipeline entrenado."""
        from datetime import datetime, timezone
        metadata = ModelMetadata(
            version=version,
            features=features,
            cluster_names=cluster_names,
            trained_at=datetime.now(timezone.utc).isoformat(),
            n_clientes_entrenamiento=n_clientes_entrenamiento,
            silhouette_score=silhouette_score,
            notas=notas,
        )
        return cls(pipeline=pipeline, metadata=metadata)

    # ----------------------------------------------------------------
    # Persistencia
    # ----------------------------------------------------------------
    @classmethod
    def load(cls, version: str, models_dir: Path | str = None) -> "SegmentadorClientes":
        """Carga un modelo congelado desde disco."""
        models_dir = _resolve_models_dir(models_dir) / version

        if not models_dir.exists():
            raise FileNotFoundError(
                f"No existe el directorio del modelo: {models_dir}. "
                f"¿Olvidaste correr el notebook 07?"
            )

        pipeline = joblib.load(models_dir / "pipeline.pkl")

        with open(models_dir / "metadata.json", "r", encoding="utf-8") as f:
            metadata = ModelMetadata.from_dict(json.load(f))

        return cls(pipeline=pipeline, metadata=metadata)

    def save(self, models_dir: Path | str = None) -> Path:
        """Guarda pipeline + metadata en `<models_dir>/<version>/`."""
        models_dir = _resolve_models_dir(models_dir) / self.metadata.version
        models_dir.mkdir(parents=True, exist_ok=True)

        joblib.dump(self.pipeline, models_dir / "pipeline.pkl")

        with open(models_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(self.metadata.to_dict(), f, indent=2, ensure_ascii=False)

        return models_dir

    # ----------------------------------------------------------------
    # Predicción
    # ----------------------------------------------------------------
    def predict(self, df: pd.DataFrame, with_distance: bool = False) -> pd.DataFrame:
        """
        Asigna segmento a cada cliente.

        Parámetros
        ----------
        df : DataFrame que DEBE contener todas las columnas en self.metadata.features
            en ESCALA ORIGINAL (sin log-transform aplicado, sin scaling).
            Puede contener columnas adicionales (se preservan en el output).
        with_distance : si True, agrega 'distancia_centroide' (útil para detectar
            clientes "fronterizos" entre segmentos).

        Retorna
        -------
        DataFrame con las columnas originales + 'cluster_id' + 'segmento_cluster'
        (y opcionalmente 'distancia_centroide').
        """
        self._validate_input(df)

        X = df[self.metadata.features].copy()
        clusters = self.pipeline.predict(X)

        out = df.copy()
        out["cluster_id"] = clusters
        out["segmento_cluster"] = [self.metadata.cluster_names[c] for c in clusters]

        if with_distance:
            # Aplicar manualmente los pasos previos al kmeans para obtener X_scaled.
            # Pasamos los DataFrames tal cual para que el scaler reconozca los nombres
            # de columnas y no emita warning.
            X_transformed = X
            for step_name, step in self.pipeline.steps[:-1]:  # todo menos kmeans
                X_transformed = step.transform(X_transformed)
            X_transformed = np.asarray(X_transformed)

            kmeans = self.pipeline.named_steps["kmeans"]
            centroides_asignados = kmeans.cluster_centers_[clusters]
            out["distancia_centroide"] = np.linalg.norm(
                X_transformed - centroides_asignados, axis=1
            )

        return out

    # ----------------------------------------------------------------
    # Inspección de centroides
    # ----------------------------------------------------------------
    def centroides_escala_original(self) -> pd.DataFrame:
        """
        Devuelve los centroides del K-Means en la escala ORIGINAL de las features
        (no en log ni escalado). Útil para naming y reporting.

        Aplica inverse_transform(scaler) y expm1 para revertir el log.
        """
        kmeans = self.pipeline.named_steps["kmeans"]
        scaler = self.pipeline.named_steps["scaler"]

        # Revertir scaler → datos en escala log
        centroides_log = scaler.inverse_transform(kmeans.cluster_centers_)

        # Revertir log → datos en escala original
        centroides_orig = np.expm1(centroides_log)

        df = pd.DataFrame(centroides_orig, columns=self.metadata.features)
        df.index.name = "cluster_id"
        return df.round(1)

    # ----------------------------------------------------------------
    # Validación
    # ----------------------------------------------------------------
    def validate_against_snapshot(
        self,
        df: pd.DataFrame,
        df_snapshot: pd.DataFrame,
        id_col: str = "cliente_id",
        label_col: str = "segmento_cluster",
    ) -> dict:
        """
        Compara las predicciones actuales contra un snapshot previo.
        Útil para detectar si el modelo (o el cálculo de features upstream) cambió.

        Retorna un dict con:
        - n_total
        - n_coincidencias
        - pct_coincidencia
        - matriz_confusion (DataFrame: filas = snapshot, columnas = actual)
        """
        df_pred = self.predict(df)

        merged = df_pred[[id_col, label_col]].merge(
            df_snapshot[[id_col, label_col]],
            on=id_col,
            how="inner",
            suffixes=("_actual", "_snapshot"),
        )

        coincidencias = (merged[f"{label_col}_actual"] == merged[f"{label_col}_snapshot"]).sum()
        total = len(merged)

        matriz = pd.crosstab(
            merged[f"{label_col}_snapshot"],
            merged[f"{label_col}_actual"],
        )

        return {
            "n_total": total,
            "n_coincidencias": int(coincidencias),
            "pct_coincidencia": float(coincidencias / total) if total else 0.0,
            "matriz_confusion": matriz,
        }

    # ----------------------------------------------------------------
    # Helpers privados
    # ----------------------------------------------------------------
    def _validate_input(self, df: pd.DataFrame) -> None:
        faltantes = [c for c in self.metadata.features if c not in df.columns]
        if faltantes:
            raise ValueError(
                f"Faltan features en el DataFrame: {faltantes}. "
                f"El modelo espera: {self.metadata.features}"
            )

        nulos = df[self.metadata.features].isnull().sum()
        if nulos.any():
            cols_con_nulos = nulos[nulos > 0].to_dict()
            raise ValueError(
                f"Hay valores nulos en features: {cols_con_nulos}. "
                f"Trátalos antes de scorear (e.g., imputación de single-buyers)."
            )

        # log1p requiere valores >= 0. Verificar para evitar NaN silenciosos.
        negativos = (df[self.metadata.features] < 0).sum()
        if negativos.any():
            cols_neg = negativos[negativos > 0].to_dict()
            raise ValueError(
                f"Hay valores negativos en features: {cols_neg}. "
                f"El pipeline aplica log1p internamente, que no soporta negativos."
            )

    def __repr__(self) -> str:
        return (
            f"SegmentadorClientes(version={self.metadata.version!r}, "
            f"features={self.metadata.features}, "
            f"clusters={list(self.metadata.cluster_names.values())})"
        )


# ----------------------------------------------------------------
# Helpers a nivel de módulo
# ----------------------------------------------------------------
def _resolve_models_dir(models_dir: Path | str | None) -> Path:
    """Resuelve el directorio de modelos. Si no se pasa, intenta usar pulse.config.paths.MODELS."""
    if models_dir is not None:
        return Path(models_dir)

    try:
        from pulse.config.paths import MODELS
        return Path(MODELS)
    except (ImportError, AttributeError) as e:
        raise ValueError(
            "No se especificó models_dir y pulse.config.paths.MODELS no está disponible. "
            "Agrega MODELS a tu config o pasa models_dir explícitamente."
        ) from e