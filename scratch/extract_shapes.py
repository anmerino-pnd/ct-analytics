import pandas as pd
import numpy as np

base_path = "C:/Users/angel.merino/Documents/ct-analytics/datos/processed/"

print("--- MBA Reglas por Segmento ---")
try:
    mba = pd.read_parquet(base_path + "mba_reglas_por_segmento.parquet")
    print(mba.head(5))
    print("Segmentos presentes:", mba['segmento'].unique())
except Exception as e:
    print(e)

print("\n--- Estacionalidad Mes ---")
try:
    est_mes = pd.read_parquet(base_path + "temporalidad_segmento_mes.parquet")
    print(est_mes.head(10))
except Exception as e:
    print(e)

print("\n--- Estacionalidad Hora Dia ---")
try:
    est_hd = pd.read_parquet(base_path + "temporalidad_segmento_hora_dia.parquet")
    print(est_hd.head(5))
except Exception as e:
    print(e)

print("\n--- Snapshot ---")
try:
    snap = pd.read_parquet(base_path + "modelo_snapshot_v1.parquet")
    print(snap['segmento_cluster'].value_counts(normalize=True))
except Exception as e:
    print(e)
