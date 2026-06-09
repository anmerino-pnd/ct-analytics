from pathlib import Path
import locale
locale.setlocale(locale.LC_TIME, "es_MX.UTF-8")


def find_project_root(start_path: Path, marker_file: str = "pyproject.toml") -> Path:
    current = start_path.resolve()
    while not (current / marker_file).exists() and current != current.parent:
        current = current.parent
    return current

BASE_DIR = find_project_root(Path(__file__))
DATA = BASE_DIR / "datos"
PROCESSED = DATA / "processed"
PROCESSED_PRUEBAS = DATA / "processed_pruebas"
MODELS = DATA / "models" / "v1"
SNAPSHOTS_DIR = PROCESSED / "snapshots"

for path in [
    DATA,
    PROCESSED,
    PROCESSED_PRUEBAS,
    MODELS,
    SNAPSHOTS_DIR,
]:
    path.mkdir(parents=True, exist_ok=True)