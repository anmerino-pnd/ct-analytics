# Qwen Context

## Project Overview

**CT Analytics** is a data analytics project built with Python, combining:

1. **FastAPI Backend**: A web application serving a Power BI dashboard via an iframe
2. **ETL Pipeline**: Data extraction, transformation, and loading modules (currently appearing empty)
3. **MongoDB Integration**: Database connectivity using PyMongo
4. **Quarto Documentation**: A Spanish-language documentation website using Quarto

### Architecture

```
ct-analytics/
├── src/pulse/
│   ├── main.py              # FastAPI application entry point
│   ├── config/
│   │   └── settings.py      # Environment-based configuration
│   └── etl/
│       ├── extraction.py    # Data extraction (currently empty)
│       ├── load.py          # Data loading (currently empty)
│       └── transform.py     # Data transformation (currently empty)
├── templates/
│   └── dashboard.html       # Power BI iframe container
├── notebooks/
│   └── 01_EDA.ipynb         # Exploratory data analysis notebook
├── docs/                    # Generated documentation
└── quarto/                  # Source documentation (QMD files)
```

### Technologies

- **Python 3.13+**
- **FastAPI** - Web framework
- **Jinja2** - Template engine
- **PyMongo** - MongoDB database driver
- **Quarto** - Documentation generator
- **dotenv** - Environment variable management

## Building and Running

### Development Setup

```bash
# Install dependencies
uv sync

# Run the FastAPI application
uv run pulse
```

### Environment Configuration

The application uses environment variables from `.env`:

| Variable | Purpose |
|----------|---------|
| `POWERBI_IFRAME_URL` | Power BI iframe source URL |
| `MONGO_URI` | MongoDB connection string |
| `MONGO_DB` | MongoDB database name |
| `MONGO_COLLECTION_PEDIDOS` | Pedidos collection name |
| `IP_DEV`, `PORT_DEV`, `USER_DEV`, `PWD_DEV` | Development credentials |

### Documentation Generation

```bash
# Generate Quarto documentation
quarto render
```

## Development Conventions

### Code Structure
- **Main Application**: `src/pulse/main.py` - FastAPI entry point
- **Configuration**: `src/pulse/config/settings.py` - Environment-based settings
- **ETL Pipeline**: `src/pulse/etl/` - Data processing modules
- **Data Analysis**: `notebooks/` - Jupyter notebooks

### Documentation
- Source documentation is maintained in `quarto/` as `.qmd` files
- Generated HTML is output to `docs/`
- Language: Spanish (`lang: es`)

### Testing
- **Notebooks**: Located in `notebooks/` directory
- Integration with Quarto documentation workflow

### Git Integration
- The project is tracked via Git
- Configuration files like `.env` are git-ignored (`.gitignore` present)

### Build System
- Uses `uv` as the Python package manager
- `pyproject.toml` defines project metadata and dependencies
- Build system: `setuptools`

## Key Files

| File | Purpose |
|------|---------|
| `src/pulse/main.py` | FastAPI app serving Power BI dashboard |
| `src/pulse/config/settings.py` | Configuration loaded from environment |
| `templates/dashboard.html` | HTML template rendering Power BI iframe |
| `quarto/_quarto.yml` | Quarto documentation configuration |
| `pyproject.toml` | Python project configuration and dependencies |
| `notebooks/01_EDA.ipynb` | Exploratory data analysis notebook |

## Current State

- **ETL Modules**: The extraction, load, and transform modules exist but appear to be empty
- **Documentation**: Partially completed with 2 active chapters (Home, Business Understanding)
- **Backend**: Working Power BI dashboard integration via iframe
- **EDA**: Notebook-based exploratory data analysis for pedidos collection
