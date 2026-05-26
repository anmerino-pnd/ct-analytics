import nbformat
import sys

sys.stdout.reconfigure(encoding='utf-8')

f = 'notebooks/ct_analytics_v1.ipynb'
nb = nbformat.read(f, as_version=4)

print("--- EDA Section ---")
for cell in nb.cells[:50]:
    if cell.cell_type == 'markdown':
        print(cell.source[:200])
