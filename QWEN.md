# Qwen Context

## Project Overview

**CT Analytics** is a data analytics project built with Python, combining:

1. **FastAPI Backend**: A web application serving a Power BI dashboard via an iframe
2. **ETL Pipeline**: Data extraction, transformation, and loading modules for processing MongoDB pedidos data
3. **Data Science Analysis**: Market Basket Analysis (Association Rules) and RFM Customer Segmentation
4. **MongoDB Integration**: Database connectivity using PyMongo
5. **Quarto Documentation**: A Spanish-language documentation website using Quarto

### Architecture

```
ct-analytics/
├── src/pulse/
│   ├── main.py              # FastAPI application entry point
│   ├── config/
│   │   ├── settings.py      # Environment-based configuration
│   │   └── paths.py         # File paths configuration
│   └── etl/
│       ├── extraction.py    # Data extraction from MongoDB
│       ├── load.py          # Data loading modules
│       └── transform.py     # Data transformation modules
├── templates/
│   └── dashboard.html       # Power BI iframe container
├── notebooks/
│   ├── 00_descubrimientos.ipynb   # Data discovery and volume analysis
│   ├── 01_EDA.ipynb               # Exploratory data analysis
│   ├── 02_EDA.ipynb               # Market Basket Analysis
│   ├── 03_RFM_analysis.ipynb      # RFM Customer Segmentation
│   └── 04_Cadencia.ipynb          # Purchase cadence analysis
├── datos/
│   └── processed/              # Parquet output files
├── docs/                       # Generated documentation
└── quarto/                     # Source documentation (QMD files)
```

### Technologies

- **Python 3.13+**
- **FastAPI** - Web framework
- **Jinja2** - Template engine
- **PyMongo** - MongoDB database driver
- **Quarto** - Documentation generator
- **Seaborn** - Data visualization
- **Matplotlib** - Data visualization
- **pandas** - Data manipulation
- **numpy** - Numerical computing
- **mlxtend** - Association rules (FP-Growth)
- **Jupyter** - Notebook-based analysis

## Building and Running

### Development Setup

```bash
# Install dependencies using uv
uv sync

# Run the FastAPI application
uv run pulse

# Access the dashboard at http://localhost:<PORT>/dashboard
```

### Environment Configuration

The application uses environment variables from `.env`:

| Variable | Purpose | Default |
|----------|---------|---------|
| `POWERBI_IFRAME_URL` | Power BI iframe source URL | Required |
| `MONGO_URI` | MongoDB connection string | Required |
| `MONGO_DB` | MongoDB database name | Required |
| `MONGO_COLLECTION_PEDIDOS` | Pedidos collection name | Required |
| `IP_DEV` | Development IP address | Optional |
| `PORT_DEV` | Development port | Optional |
| `USER_DEV` | Development database user | Optional |
| `PWD_DEV` | Development database password | Optional |
| `DB_DEV` | Development database name | Optional |

### Documentation Generation

```bash
# Generate Quarto documentation in Spanish
quarto render
```

### Data Processing Pipeline

```bash
# Extract and transform data for analysis
uv run python src/pulse/etl/extraction.py
uv run python src/pulse/etl/transform.py
uv run python src/pulse/etl/load.py
```

## Data Discovery Findings

### Database Volume Analysis

The `pedidos` collection contains:

| Year | Volume | Notes |
|------|--------|-------|
| 2023 | ~340K | Consistent volume |
| 2024 | ~342K | Consistent volume |
| 2025 | ~43K | **Abrupt drop** (99.7% decrease from March 2025) |

### Key Observations

1. **Data Integrity**: 99.99% valid (no date type issues)
2. **Date Format**: ISODate (not string or null)
3. **Decision**: Analysis focuses on **2024 data** due to 2025 data gap
4. **Distribution**: ~25K-31K orders/month in 2024 (stable pattern)

### Data Schema

```json
{
  "pedido": {
    "tipo": "CTonline",
    "fecha": ISODate
  },
  "encabezado": {
    "cliente": String,
    "nombre": String,
    "plazo": String,
    "tipoPago": String
  },
  "detalle": {
    "producto": [{
      "clave": String,
      "cantidad": Number,
      "precio": Number,
      "precioFinal": Number,
      "moneda": String
    }]
  },
  "errores": [...]
}
```

## Data Science Analysis

### 1. Market Basket Analysis (MBA)

**Objective**: Identify cross-selling opportunities through association rules

**Methodology**: FP-Growth algorithm based on *Data Science for Business* — Foster Provost & Tom Fawcett

#### Data Preparation

| Dataset | Rows | Columns | Unique Products |
|---------|------|---------|-----------------|
| `orders_2024.parquet` | 233,277 | 9 | - |
| `items_2024.parquet` | 550,983 | 8 | 7,353 |

**Filtering Process**:
- Remove single-product orders (48.6% → 113,328 orders)
- Min product frequency threshold: 30 appearances
- Final valid orders: 102,913
- Final products: 1,637

#### Association Rules Metrics

| Metric | Definition |
|--------|------------|
| Support | Fraction of orders containing the itemset |
| Confidence | P(B \| A) — if A is bought, how likely is B? |
| Lift | Co-compare frequency vs expected by chance (lift > 1 = real association) |

#### Key Findings

- **Total Rules**: 318 rules with lift > 1.2
- **Cross-Category Rules**: 30 rules (9.4% of total) — **most actionable**
- **Same-Family Rules**: 288 rules (90.6% of total) — expected behavior
- **Top Cross-Category Example**:
  ```
  ACCDAH650 → GRDDAH920
  Support: 0.58% | Confidence: 18.5% | Lift: 14.59
  ```

#### Product Families (281 total)

| Family | Count |
|--------|-------|
| CAR | 78,123 |
| ACC | 60,680 |
| MEM | 57,039 |
| DDU | 34,033 |
| CAB | 15,916 |
| MOU | 14,927 |
| ESD | 11,613 |
| KIT | 10,569 |
| CAM | 9,300 |
| GAB | 8,677 |

#### Actionable Marketing Rules (confidence > 30%, lift > 2)

| Antecedent | Consequent | Support | Confidence | Lift |
|------------|------------|---------|------------|------|
| ACCPVS040 | ACCDAH650, ACCPVS260 | 0.84% | 30.2% | 31.59 |
| ACCPVS260 | ACCDAH650, ACCPVS040 | 0.84% | 37.6% | 30.08 |
| ACCDAH650 | GRDDAH920 | 0.58% | 18.5% | 14.59 |
| CAMDAH4730 | ACCDAH650 | 0.81% | 25.8% | 14.03 |

### 2. RFM Customer Segmentation

**Objective**: Segment customers using Recency-Frequency-Monetary model

**Methodology**: RFM Scoring based on quintiles, referenced in *Data Science for Business* — Foster Provost & Tom Fawcett

#### RFM Metrics

| Dimension | Question | Best Value |
|-----------|----------|------------|
| **Recency (R)** | When was last purchase? | More recent = better |
| **Frequency (F)** | How many purchases? | More frequent = better |
| **Monetary (M)** | Total spending? | More spending = better |

#### Data Summary

| Metric | Value |
|--------|-------|
| Orders Analyzed | 233,277 |
| Items Analyzed | 550,983 |
| Unique Customers | 14,074 |
| Revenue (2024) | $271,239,112 |

#### RFM Scores (1-5 per dimension)

| Score | Meaning |
|-------|---------|
| R: 5 | Last purchase very recent (< 25% of customers) |
| F: 5 | Most frequent buyers (< 20% of customers) |
| M: 5 | Top spenders (< 20% of customers) |

#### Customer Segments (7 segments based on R+F combinations)

| Segment | Description | Customers | Revenue | % Customers | % Revenue |
|---------|-------------|-----------|---------|-------------|-----------|
| **MVPs** | High frequency, recent, high spend | 4,118 | $214,043,074 | 29.3% | **78.9%** |
| **Leales** | Medium-high frequency, good spend | 2,714 | $30,591,803 | 19.3% | 11.3% |
| **Necesitan atención** | Medium frequency, not recent | 2,922 | $11,671,475 | 20.8% | 4.3% |
| **En riesgo** | High historical frequency, not returning | 484 | $7,395,679 | 3.4% | 2.7% |
| **Hibernando** | Low frequency, not recent | 2,199 | $3,356,306 | 15.6% | 1.2% |
| **Prometedores** | Recent, low frequency | 926 | $2,217,597 | 6.6% | 0.8% |
| **Nuevos** | Recent, 1-3 purchases | 711 | $1,963,178 | 5.1% | 0.7% |

#### Key Insight: MVPs + Leales = 90.2% of revenue

### 3. Purchase Cadence Analysis

**Objective**: Analyze habitual purchase patterns beyond simple recency

#### Cadence Calculation

- **Metric**: Average days between purchases per customer
- **Applicable**: 11,142 customers (those with 2+ purchases)
- **Median**: ~12.1 days between purchases

#### Urgency Ratio

**Formula**: `ratio_urgencia = recency / cadencia_habitual`

| Ratio Range | Meaning |
|-------------|---------|
| < 1 | A tiempo (just purchased) |
| 1 - 2 | Normal (within expected window) |
| 2 - 3 | Warning (behind schedule) |
| > 3 | **Alert** (possible churn) |

#### Urgent Customers for Reactivation

- **Count**: 1,507 customers
- **Criteria**: ratio_urgencia > 2 AND frequency ≥ 10 AND monetary > median
- **Top Example**:
  ```
  Customer: HMO0009 (ELENA GONZALEZ)
  Segment: MVPs
  Recency: 3 days | Cadence: 0.15 days | Ratio: 19.87
  Monetary: $1,308,378
  ```

## Development Conventions

### Code Structure
- **Main Application**: `src/pulse/main.py` - FastAPI entry point
- **Configuration**: `src/pulse/config/settings.py` - Environment-based settings
- **ETL Pipeline**: `src/pulse/etl/` - Data processing modules
- **Data Analysis**: `notebooks/` - Jupyter notebooks for exploratory analysis

### Documentation
- Source documentation is maintained in `quarto/` as `.qmd` files
- Generated HTML is output to `docs/`
- Language: Spanish (`lang: es`)
- Theme: cosmo (light) / darkly (dark)

### Git Integration
- The project is tracked via Git
- Configuration files like `.env` are git-ignored (`.gitignore` present)

### Build System
- Uses `uv` as the Python package manager
- `pyproject.toml` defines project metadata and dependencies
- Build system: `setuptools`

### Data Processing
- All ETL functions use batch processing (`batch_size: int = 5000`)
- Date ranges are specified in ISO format (YYYY-MM-DD)
- MongoDB queries use `$or` and `$nor` operators for complex filtering
- Projection fields are explicitly defined to reduce document size

## Database Schema

The ETL module queries the `pedidos` collection from MongoDB with the following structure:

```json
{
  "pedido": {
    "tipo": "CTonline",
    "fecha": ISODate
  },
  "encabezado": {
    "cliente": String,
    "nombre": String,
    "plazo": String,
    "tipoPago": String
  },
  "detalle": {
    "producto": [{
      "clave": String,
      "cantidad": Number,
      "precio": Number,
      "precioFinal": Number,
      "moneda": String
    }]
  },
  "errores": [...]
}
```

## Current State

- **ETL Modules**: The extraction, load, and transform modules are fully implemented
- **Documentation**: Partially completed with 2 active chapters (Home, Business Understanding)
- **Backend**: Working Power BI dashboard integration via iframe
- **EDA**: Notebook-based exploratory data analysis for pedidos collection
- **Documentation Language**: Spanish
- **Analysis Focus**: 2024 data due to 2025 data gap (99.7% drop from March 2025)

## Key Insights Summary

### Market Basket Analysis
- **318 association rules** with lift > 1.2
- **30 cross-category rules** (most actionable for marketing)
- Top cross-category: ACCDAH650 ↔ GRDDAH920 (lift 14.59)

### RFM Segmentation
- **14,074 customers** segmented into 7 groups
- **MVPs**: 29.3% of customers generate **78.9% of revenue**
- **Leales**: 19.3% generate 11.3% of revenue
- Combined MVPs + Leales = **90.2% of total revenue**

### Customer Reactivation
- **1,507 urgent customers** identified (ratio_urgencia > 2)
- Top priority: MVPs and Leales who haven't purchased in their expected cadence
- Example: HMO0009 (MVP, $1.3M revenue) with ratio_urgencia = 19.87
