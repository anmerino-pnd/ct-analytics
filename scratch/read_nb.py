import nbformat
import sys

sys.stdout.reconfigure(encoding='utf-8')

files = [
    'notebooks/05_mba_por_segmento.ipynb',
    'notebooks/06_estacionalidad_por_segmento.ipynb',
    'notebooks/07_persistir_modelo.ipynb'
]

for f in files:
    print(f"\n--- {f} ---")
    try:
        nb = nbformat.read(f, as_version=4)
        for cell in nb.cells:
            if cell.cell_type in ('markdown', 'code'):
                print(cell.source)
    except Exception as e:
        print(f"Error reading {f}: {e}")
