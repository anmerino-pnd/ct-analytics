"""
Tests para pulse.modeling.segmentador (v2 con pipeline interno).

Estos tests garantizan:
1. El wrapper round-trip funciona: lo que guardas es lo que cargas.
2. Las predicciones son determinísticas (mismo input → mismo output).
3. La validación de input falla apropiadamente cuando faltan features, hay NaNs, o negativos.
4. La validación contra snapshot da 100% en self-test.
5. CRÍTICO: el pipeline aplica log-transform internamente; el wrapper produce los
   mismos clusters que se obtienen entrenando el pipeline directamente.

Ejecutar con: pytest tests/test_segmentador.py -v
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.cluster import KMeans
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

from pulse.modeling.segmentador import (
    ModelMetadata,
    SegmentadorClientes,
    build_pipeline,
)


# ----------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------
@pytest.fixture
def sample_data() -> pd.DataFrame:
    """
    Dataset sintético con distribuciones SESGADAS (estilo RFM real),
    para garantizar que el log-transform realmente importe.
    """
    rng = np.random.default_rng(seed=42)
    n = 200
    return pd.DataFrame({
        "cliente_id": [f"C{i:04d}" for i in range(n)],
        "recency": rng.integers(1, 500, size=n).astype(float),
        # frequency con cola larga (estilo Poisson)
        "frequency": rng.poisson(lam=5, size=n).astype(float) + 1,
        # monetary muy sesgado (estilo log-normal)
        "monetary": np.exp(rng.normal(loc=8, scale=1.2, size=n)),
        "dias_entre_compras": rng.uniform(5, 200, size=n),
    })


@pytest.fixture
def trained_segmentador(sample_data) -> SegmentadorClientes:
    """Entrenamos un SegmentadorClientes con datos sintéticos."""
    features = ["recency", "frequency", "monetary", "dias_entre_compras"]
    X = sample_data[features]

    pipeline = build_pipeline()
    pipeline.fit(X)

    return SegmentadorClientes.from_fitted(
        pipeline=pipeline,
        version="test",
        features=features,
        cluster_names={0: "A", 1: "B", 2: "C", 3: "D", 4: "E"},
        n_clientes_entrenamiento=len(sample_data),
    )


@pytest.fixture
def tmp_models_dir() -> Path:
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


# ----------------------------------------------------------------
# Tests
# ----------------------------------------------------------------
class TestPredict:
    def test_predict_returns_required_columns(self, trained_segmentador, sample_data):
        result = trained_segmentador.predict(sample_data)
        assert "cluster_id" in result.columns
        assert "segmento_cluster" in result.columns

    def test_predict_preserves_input_columns(self, trained_segmentador, sample_data):
        result = trained_segmentador.predict(sample_data)
        for col in sample_data.columns:
            assert col in result.columns

    def test_predict_is_deterministic(self, trained_segmentador, sample_data):
        r1 = trained_segmentador.predict(sample_data)
        r2 = trained_segmentador.predict(sample_data)
        pd.testing.assert_series_equal(r1["cluster_id"], r2["cluster_id"])
        pd.testing.assert_series_equal(r1["segmento_cluster"], r2["segmento_cluster"])

    def test_predict_assigns_all_clusters(self, trained_segmentador, sample_data):
        result = trained_segmentador.predict(sample_data)
        assert result["cluster_id"].nunique() == 5

    def test_predict_with_distance(self, trained_segmentador, sample_data):
        result = trained_segmentador.predict(sample_data, with_distance=True)
        assert "distancia_centroide" in result.columns
        assert (result["distancia_centroide"] >= 0).all()


class TestInputValidation:
    def test_predict_fails_on_missing_feature(self, trained_segmentador, sample_data):
        df_incomplete = sample_data.drop(columns=["monetary"])
        with pytest.raises(ValueError, match="Faltan features"):
            trained_segmentador.predict(df_incomplete)

    def test_predict_fails_on_nulls(self, trained_segmentador, sample_data):
        df_with_nulls = sample_data.copy()
        df_with_nulls.loc[0, "dias_entre_compras"] = np.nan
        with pytest.raises(ValueError, match="nulos"):
            trained_segmentador.predict(df_with_nulls)

    def test_predict_fails_on_negatives(self, trained_segmentador, sample_data):
        df_with_neg = sample_data.copy()
        df_with_neg.loc[0, "recency"] = -1
        with pytest.raises(ValueError, match="negativos"):
            trained_segmentador.predict(df_with_neg)

    def test_predict_accepts_extra_columns(self, trained_segmentador, sample_data):
        df_extra = sample_data.copy()
        df_extra["columna_extra"] = "hola"
        result = trained_segmentador.predict(df_extra)
        assert "columna_extra" in result.columns


class TestPersistence:
    def test_save_creates_expected_files(self, trained_segmentador, tmp_models_dir):
        trained_segmentador.save(models_dir=tmp_models_dir)
        version_dir = tmp_models_dir / "test"
        assert (version_dir / "pipeline.pkl").exists()
        assert (version_dir / "metadata.json").exists()

    def test_metadata_is_valid_json(self, trained_segmentador, tmp_models_dir):
        trained_segmentador.save(models_dir=tmp_models_dir)
        with open(tmp_models_dir / "test" / "metadata.json") as f:
            data = json.load(f)
        assert data["version"] == "test"
        assert "features" in data
        assert "cluster_names" in data

    def test_load_roundtrip(self, trained_segmentador, sample_data, tmp_models_dir):
        trained_segmentador.save(models_dir=tmp_models_dir)
        loaded = SegmentadorClientes.load(version="test", models_dir=tmp_models_dir)

        original_pred = trained_segmentador.predict(sample_data)
        loaded_pred = loaded.predict(sample_data)

        pd.testing.assert_series_equal(
            original_pred["cluster_id"], loaded_pred["cluster_id"]
        )
        pd.testing.assert_series_equal(
            original_pred["segmento_cluster"], loaded_pred["segmento_cluster"]
        )

    def test_load_fails_on_missing_version(self, tmp_models_dir):
        with pytest.raises(FileNotFoundError):
            SegmentadorClientes.load(version="no_existe", models_dir=tmp_models_dir)


class TestValidateAgainstSnapshot:
    def test_self_validation_is_100_pct(self, trained_segmentador, sample_data):
        snapshot = trained_segmentador.predict(sample_data)[
            ["cliente_id", "segmento_cluster"]
        ]
        result = trained_segmentador.validate_against_snapshot(
            df=sample_data,
            df_snapshot=snapshot,
        )
        assert result["pct_coincidencia"] == 1.0
        assert result["n_coincidencias"] == result["n_total"]

    def test_returns_confusion_matrix(self, trained_segmentador, sample_data):
        snapshot = trained_segmentador.predict(sample_data)[
            ["cliente_id", "segmento_cluster"]
        ]
        result = trained_segmentador.validate_against_snapshot(
            df=sample_data,
            df_snapshot=snapshot,
        )
        assert isinstance(result["matriz_confusion"], pd.DataFrame)


class TestPipelineIntegrity:
    """
    Tests críticos que detectan bugs como el del v1 (donde el log-transform
    quedaba fuera del wrapper y el predict daba clusters absurdos).
    """

    def test_wrapper_matches_direct_pipeline_predict(self, sample_data):
        """
        El wrapper.predict() debe dar los mismos clusters que entrenar
        un pipeline y llamarle .predict() directamente. Si esto falla,
        algún paso del pipeline no se está aplicando en predicción.
        """
        features = ["recency", "frequency", "monetary", "dias_entre_compras"]
        X = sample_data[features]

        pipeline = build_pipeline()
        pipeline.fit(X)

        clusters_directos = pipeline.predict(X)

        seg = SegmentadorClientes.from_fitted(
            pipeline=pipeline,
            version="integrity",
            features=features,
            cluster_names={i: f"C{i}" for i in range(5)},
            n_clientes_entrenamiento=len(sample_data),
        )
        clusters_wrapper = seg.predict(sample_data)["cluster_id"].values

        np.testing.assert_array_equal(
            clusters_directos, clusters_wrapper,
            err_msg=(
                "El wrapper produce clusters distintos al pipeline directo. "
                "Probablemente algún paso (log, scaler) no se está aplicando "
                "en predict()."
            ),
        )

    def test_cluster_distribution_is_balanced(self, trained_segmentador, sample_data):
        """
        Sanity check: con datos sintéticos balanceados, ningún cluster
        debería absorber >70% de los puntos. Si esto pasa, hay un bug
        de pipeline (escalas distintas en fit y predict).
        """
        result = trained_segmentador.predict(sample_data)
        pct_mayor = result["cluster_id"].value_counts(normalize=True).max()
        assert pct_mayor < 0.7, (
            f"Un cluster absorbió {pct_mayor:.1%} de los datos. "
            "Esto sugiere que las escalas de fit y predict no coinciden."
        )

    def test_centroides_escala_original_returns_valid_values(self, trained_segmentador):
        """Los centroides invertidos deben estar en rangos plausibles."""
        c = trained_segmentador.centroides_escala_original()
        assert (c >= 0).all().all(), "Los centroides en escala original deben ser >= 0"
        assert not c.isnull().any().any(), "No debe haber NaN en los centroides"