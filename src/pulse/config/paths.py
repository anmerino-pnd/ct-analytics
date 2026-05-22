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
MODELS = DATA / "models"

for path in [
    DATA,
    PROCESSED,
    MODELS
]:
    path.mkdir(parents=True, exist_ok=True)