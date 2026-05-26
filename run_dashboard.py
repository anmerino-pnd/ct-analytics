"""Arranque del dashboard de segmentación de clientes.

Uso:
    uv run python run_dashboard.py
"""
from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run(
        "pulse.dashboard.app:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
    )


if __name__ == "__main__":
    main()
