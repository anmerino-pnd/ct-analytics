import nbformat
import sys

sys.stdout.reconfigure(encoding='utf-8')

f = 'notebooks/ct_analytics_v1.ipynb'
try:
    nb = nbformat.read(f, as_version=4)
    print(f"Total cells: {len(nb.cells)}")
    for i, cell in enumerate(nb.cells):
        if cell.cell_type == 'markdown':
            # Print only headers or short markdown to get an idea of the structure
            lines = cell.source.split('\n')
            headers = [line for line in lines if line.startswith('#')]
            if headers:
                print(f"Cell {i} Markdown Headers:\n" + "\n".join(headers))
        elif cell.cell_type == 'code':
            # Optionally print the first few lines of code to understand what is being computed
            lines = cell.source.split('\n')
            first_lines = lines[:5]
            if any("groupby" in line or "plot" in line or "rfm" in line.lower() or "kmeans" in line.lower() for line in lines):
                print(f"Cell {i} Code Snippet:\n" + "\n".join(first_lines) + "\n...")
except Exception as e:
    print(f"Error reading {f}: {e}")
