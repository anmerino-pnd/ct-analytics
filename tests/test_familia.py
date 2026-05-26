"""
Tests para pulse.analytics.familia.

Cubre:
1. Derivación correcta de la regla clave → familia.
2. Manejo de casos límite (None, NaN, cadenas vacías).
3. Validación de input (columna 'clave' obligatoria).
4. Recálculo si la columna ya existe.

Ejecutar con: pytest tests/test_familia.py -v
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pulse.analytics.familia import agregar_familia, derivar_familia


class TestDerivarFamilia:
    @pytest.mark.parametrize("clave,esperado", [
        # En la data real, los dígitos siempre van al final.
        # La regla "quitar todos los dígitos" es equivalente a
        # "quitar dígitos al final" para nuestro universo de claves.
        ("PAQLOC010", "PAQLOC"),
        ("MEMKGN3200", "MEMKGN"),
        ("CAMDAH", "CAMDAH"),       # sin dígitos: queda igual
        ("ESDKPK", "ESDKPK"),       # sin dígitos: queda igual
        ("IMPNTE", "IMPNTE"),
        ("CJNNTE3", "CJNNTE"),
    ])
    def test_deriva_correctamente(self, clave, esperado):
        assert derivar_familia(clave) == esperado

    def test_clave_none_retorna_none(self):
        assert derivar_familia(None) is None

    def test_clave_nan_retorna_none(self):
        assert derivar_familia(np.nan) is None

    def test_clave_vacia_retorna_cadena_vacia(self):
        assert derivar_familia("") == ""

    def test_clave_solo_digitos_retorna_cadena_vacia(self):
        assert derivar_familia("12345") == ""


class TestAgregarFamilia:
    def test_agrega_columna_familia(self):
        df = pd.DataFrame({
            "clave": ["PAQLOC010", "MEMKGN3200", "ESDKPK"],
        })
        resultado = agregar_familia(df)
        assert "familia" in resultado.columns
        assert resultado["familia"].tolist() == ["PAQLOC", "MEMKGN", "ESDKPK"]

    def test_no_muta_dataframe_original(self):
        df = pd.DataFrame({"clave": ["PAQLOC010"]})
        agregar_familia(df)
        assert "familia" not in df.columns

    def test_preserva_otras_columnas(self):
        df = pd.DataFrame({
            "clave": ["PAQLOC010"],
            "cantidad": [3],
            "precio_mxn": [150.0],
        })
        resultado = agregar_familia(df)
        assert "cantidad" in resultado.columns
        assert "precio_mxn" in resultado.columns

    def test_falla_sin_columna_clave(self):
        df = pd.DataFrame({"otra_col": ["x"]})
        with pytest.raises(ValueError, match="clave"):
            agregar_familia(df)

    def test_recalcula_si_columna_familia_existe(self):
        """Si llega un DataFrame con familia preexistente y mal calculada,
        agregar_familia debe sobreescribirla con el valor correcto."""
        df = pd.DataFrame({
            "clave": ["PAQLOC010"],
            "familia": ["valor_incorrecto"],
        })
        resultado = agregar_familia(df)
        assert resultado["familia"].iloc[0] == "PAQLOC"

    def test_maneja_claves_nulas(self):
        df = pd.DataFrame({
            "clave": ["PAQLOC010", None, "ESDKPK"],
        })
        resultado = agregar_familia(df)
        assert resultado["familia"].iloc[0] == "PAQLOC"
        assert pd.isna(resultado["familia"].iloc[1])  # None o NaN, ambos válidos
        assert resultado["familia"].iloc[2] == "ESDKPK"

    def test_dataframe_vacio(self):
        df = pd.DataFrame({"clave": []}, dtype=object)
        resultado = agregar_familia(df)
        assert len(resultado) == 0
        assert "familia" in resultado.columns