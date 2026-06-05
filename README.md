# Pulse — Customer Analytics Platform

![Status](https://img.shields.io/badge/status-production-green)
![Python](https://img.shields.io/badge/python-3.13+-blue?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-Proprietary-red)
![Tests](https://img.shields.io/badge/tests-60+_passing-brightgreen)
![Pipeline](https://img.shields.io/badge/pipeline-daily_cron-orange)
![Deployment](https://img.shields.io/badge/deployment-on--premise-blueviolet)

![FastAPI](https://img.shields.io/badge/FastAPI-005571?logo=fastapi)
![DuckDB](https://img.shields.io/badge/DuckDB-FFF000?logo=duckdb&logoColor=black)
![scikit-learn](https://img.shields.io/badge/scikit--learn-F7931E?logo=scikit-learn&logoColor=white)
![MongoDB](https://img.shields.io/badge/MongoDB-47A248?logo=mongodb&logoColor=white)
![Plotly](https://img.shields.io/badge/Plotly-3F4F75?logo=plotly&logoColor=white)
![AlmaLinux](https://img.shields.io/badge/AlmaLinux-9.4-0F4266?logo=almalinux&logoColor=white)
![uv](https://img.shields.io/badge/uv-managed-DE5FE9)

> Plataforma analítica end-to-end para segmentación de clientes, market basket analysis y monitoreo operativo. **De notebooks exploratorios a un dashboard productivo corriendo diariamente sin intervención.**

📊 **Portfolio público:** [anmerino-pnd.github.io/ct-analytics](https://anmerino-pnd.github.io/ct-analytics/0_home.html)

---

## Tabla de contenidos

- [¿Qué es Pulse?](#qué-es-pulse)
- [Capacidades](#capacidades)
- [Stack tecnológico](#stack-tecnológico)
- [Arquitectura](#arquitectura)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Instalación rápida](#instalación-rápida)
- [Uso](#uso)
- [Cifras clave](#cifras-clave)
- [Decisiones técnicas](#decisiones-técnicas)
- [Testing](#testing)
- [Deployment a producción](#deployment-a-producción)
- [Operación diaria](#operación-diaria)
- [Documentación adicional](#documentación-adicional)
- [Roadmap](#roadmap)
- [Autores](#autores)

---

## ¿Qué es Pulse?

Pulse es una **plataforma de Customer Analytics** construida para CT Internacional. Cubre el ciclo completo desde la ingesta de datos transaccionales desde MongoDB hasta un dashboard interactivo consumido por el equipo de marketing.

El sistema corre sobre un servidor on-premise AlmaLinux, ejecuta un pipeline ETL diario, sirve siete vistas analíticas distintas, y monitorea automáticamente la salud del modelo de segmentación. **No es un notebook — es un servicio en producción.**

### El problema que resuelve

Antes de Pulse, las estrategias de marketing en CT Internacional se diseñaban de forma reactiva, en respuesta a las solicitudes y presupuestos de los proveedores. La pregunta "¿quién compra qué, cuándo, y cómo se distingue de los demás?" se respondía con análisis ad-hoc que demoraban días y no se podían reproducir.

Pulse responde esas preguntas en **menos de un segundo** por consulta, con datos actualizados a las 3am del mismo día.

---

## Capacidades

### Análisis

- **Segmentación de clientes** con K-Means (k=5) sobre features RFM + cadencia personalizada.
- **Market Basket Analysis** ejecutado de forma independiente por segmento, con umbrales adaptativos según el tamaño del cluster.
- **Análisis de estacionalidad** con granularidad hora-día-mes en zona horaria local (CDMX).
- **Sistema de alertas** para clientes valiosos en riesgo de abandono, basado en el ratio recency / cadencia personalizada.

### Productización

- **Pipeline ETL incremental** con watermarks, validaciones de calidad automáticas y manejo de drift.
- **Dashboard web** con siete vistas interactivas (Overview, Bundles, Estacionalidad, Comparador, Heatmap Bundles, Alertas, Cliente).
- **Modelo congelado y versionado** (`v1`), con snapshot para detección de drift.
- **Servicio supervisado por systemd** con auto-restart, supervivencia a reboots y firewalld configurado.
- **Cron diario** para mantener los datos frescos sin intervención del desarrollador.

---

## Stack tecnológico

| Capa                         | Componente                  | Justificación                                            |
| ---------------------------- | --------------------------- | --------------------------------------------------------- |
| **Lenguaje**           | Python 3.13+                | Estándar de facto para data science y data engineering   |
| **Gestor de paquetes** | `uv`                      | Resolución de dependencias 10-100x más rápida que pip  |
| **Análisis**          | pandas, numpy, scikit-learn | Stack maduro y bien documentado                           |
| **ML específico**     | mlxtend (FP-Growth)         | Implementación estable de market basket analysis         |
| **Web framework**      | FastAPI + Uvicorn           | Endpoints async, validación automática, soporte OpenAPI |
| **Motor SQL**          | DuckDB                      | Lee Parquets sin cargar a memoria, SQL completo, embebido |
| **Frontend**           | Jinja2 + Plotly.js          | Server-side rendering con visualizaciones interactivas    |
| **Persistencia**       | Parquet                     | Formato columnar, compresión, lecturas selectivas        |
| **Fuente de datos**    | MongoDB                     | Cliente existente en el ecosistema de CT                  |
| **Sistema operativo**  | AlmaLinux 9                 | RHEL-compatible, soporte hasta 2032                       |
| **Supervisión**       | systemd + cron              | Native de Linux, sin dependencias adicionales             |
| **Firewall**           | firewalld                   | Estándar en RHEL/AlmaLinux                               |
| **Testing**            | pytest                      | Estándar en Python, 60+ tests en el proyecto             |

---

## Arquitectura

```mermaid
flowchart LR
    A[MongoDB<br/>Transacciones] -->|ingest incremental| B[ETL Pipeline]
    B --> C[orders_historicos.parquet<br/>items_historicos.parquet]
    C --> D[Segmentación<br/>K-Means k=5]
    D --> E[MBA<br/>FP-Growth por segmento]
    D --> F[Temporalidad<br/>hora-día-mes]
    E --> G[7 Parquets analíticos]
    F --> G
    D --> G
    G --> H[Dashboard FastAPI<br/>+ DuckDB + Plotly]
    H --> I[Marketing]

    M[Modelo v1 congelado<br/>pipeline.pkl] -.->|predict| D

    style A fill:#e3f2fd
    style M fill:#fff3e0
    style H fill:#e8f5e9
    style I fill:#f3e5f5
```

### Flujo de datos

1. **3:00 AM (cron)**: el pipeline `daily` se dispara. Lee el watermark, extrae solo pedidos nuevos de MongoDB.
2. **Pipeline**: aplica segmentación con el modelo congelado, recalcula agregados temporales, genera los 7 parquets de output.
3. **systemd**: mantiene el servicio FastAPI corriendo permanentemente con auto-restart.
4. **Usuario**: abre el dashboard en su navegador → FastAPI sirve HTML con datos embebidos → JavaScript consulta `/api/*` cuando cambia filtros → DuckDB ejecuta queries sobre Parquets → Plotly renderiza visualizaciones.

---

## Estructura del proyecto

```
ct-analytics/
├── src/pulse/
│   ├── config/
│   │   └── paths.py              # Rutas centralizadas
│   ├── etl/
│   │   ├── extraction.py         # Extracción desde MongoDB
│   │   ├── transform.py          # build_both_dfs + enrich_items
│   │   ├── load.py               # save_parquet
│   │   ├── incremental.py        # leer_watermark + extract_incremental
│   │   └── ingest.py             # run_ingest con IngestResult
│   ├── analytics/
│   │   ├── familia.py            # Derivar familia desde clave de producto
│   │   ├── rfm.py                # calcular_rfm_completo + imputación
│   │   ├── segmentacion.py       # segmentar_clientes (carga + predict)
│   │   ├── mba.py                # calcular_mba por segmento
│   │   └── temporalidad.py       # Agregados hora/día/mes + bundles
│   ├── modeling/
│   │   └── segmentador.py        # SegmentadorClientes (wrapper sklearn)
│   ├── pipeline/
│   │   ├── __main__.py           # python -m pulse.pipeline
│   │   ├── cli.py                # parser de argumentos
│   │   ├── runner.py             # orquestador (daily/weekly/monthly)
│   │   └── validacion.py         # quality checks
│   └── dashboard/
│       ├── app.py                # FastAPI app
│       ├── db.py                 # DuckDB + registro de vistas
│       ├── queries.py            # Queries SQL parametrizadas
│       ├── routers/
│       │   ├── api.py            # Endpoints JSON
│       │   └── pages.py          # Endpoints HTML
│       ├── templates/            # Jinja2 templates (7 vistas)
│       └── static/
│           ├── css/styles.css
│           └── js/{charts,filters}.js
│
├── datos/
│   ├── processed/                # Producción (10 parquets)
│   │   ├── orders_historicos.parquet
│   │   ├── items_historicos.parquet
│   │   ├── modelo_snapshot_v1.parquet
│   │   ├── clientes_segmentados.parquet
│   │   ├── mba_accionables.parquet
│   │   ├── mba_por_segmento.parquet
│   │   ├── mba_exclusivas.parquet
│   │   ├── temp_hora_dia.parquet
│   │   ├── temp_mensual.parquet
│   │   └── temp_bundles.parquet
│   └── processed_pruebas/        # Auditoría histórica
│
├── models/v1/
│   ├── pipeline.pkl              # Modelo congelado (joblib)
│   └── metadata.json             # Versión, features, mapeo cluster→nombre
│
├── tests/                        # 60+ tests (pytest)
├── logs/                         # Logs de pipeline + dashboard
├── notebooks/                    # Análisis exploratorios originales
├── quarto/                       # Sitio del portfolio (Quarto)
│
├── pyproject.toml                # Declaración del paquete + dependencias
├── uv.lock                       # Lockfile reproducible
├── .env                          # Credenciales (NUNCA en git)
├── .gitignore
└── README.md
```

---

## Instalación rápida

### Requisitos

- Python 3.13+
- `uv` instalado ([instrucciones oficiales](https://docs.astral.sh/uv/getting-started/installation/))
- Acceso a MongoDB (lectura)
- 8 GB de RAM mínimo (el pipeline carga ~1.8M items en memoria)

### Setup en 4 comandos

```bash
# 1. Clonar
git clone https://github.com/anmerino-pnd/ct-analytics ct-analytics
cd ct-analytics

# 2. Instalar dependencias
uv sync

# 3. Configurar .env (ver sección "Configuración" abajo)
cp .env.example .env
nano .env

# 4. Primera corrida (genera los 7 parquets de output)
uv run python -m pulse.pipeline weekly --log-file logs/primera_corrida.log
```

### Configuración

Crea un archivo `.env` en la raíz del proyecto:

```env
# MongoDB
MONGO_URI=mongodb://usuario:password@host:puerto/db
MONGO_DB=nombre_database
MONGO_COLLECTION=nombre_collection

# Zona horaria local para agregados temporales
TIMEZONE_LOCAL=America/Mexico_City
```

> [!WARNING]
> **Nunca subir `.env` a git.** Está en `.gitignore` por default. Si por accidente lo subes, rota las credenciales de MongoDB inmediatamente.

---

## Uso

### Ejecutar el pipeline manualmente

```bash
# Modo daily: ingest + segmentación + temporalidad (~30s)
uv run python -m pulse.pipeline daily

# Modo weekly: daily + recálculo completo de MBA (~45s)
uv run python -m pulse.pipeline weekly

# Modo monthly: weekly + validación de drift (~60s)
uv run python -m pulse.pipeline monthly

# Saltar la ingesta (cuando solo quieres recalcular agregados)
uv run python -m pulse.pipeline weekly --skip-ingest

# Especificar archivo de log
uv run python -m pulse.pipeline daily --log-file logs/manual.log
```

### Arrancar el dashboard localmente

```bash
uv run uvicorn pulse.dashboard.app:app --host 0.0.0.0 --port 8765 --reload
```

Abre en el navegador: `http://localhost:8765`

> [!TIP]
> El flag `--reload` recarga el servidor automáticamente cuando cambias código. Útil en desarrollo. **No usar en producción** — usar systemd.

### Las 7 vistas del dashboard

| Vista           | URL                                    | Responde                                            |
| --------------- | -------------------------------------- | --------------------------------------------------- |
| Overview        | `/dashboard/overview`                | ¿Cómo está distribuida nuestra base de clientes? |
| Bundles         | `/dashboard/bundles`                 | ¿Qué productos puedo agrupar y a quién?          |
| Estacionalidad  | `/dashboard/estacionalidad`          | ¿Cuándo lanzar campañas?                         |
| Comparador      | `/dashboard/comparador`              | ¿Cómo se diferencian dos segmentos?               |
| Heatmap Bundles | `/dashboard/heatmap-bundles`         | ¿Cuándo se venden los bundles principales?        |
| Alertas         | `/dashboard/alertas`                 | ¿Qué clientes valiosos están en riesgo?          |
| Cliente         | `/dashboard/cliente?id=<cliente_id>` | ¿Quién es este cliente específico?               |

---

## Cifras clave

| Métrica                                   | Valor                       |
| ------------------------------------------ | --------------------------- |
| Clientes únicos analizados                | 18,638                      |
| Pedidos en histórico                      | ~780K                       |
| Pedidos en ventana de análisis (30 meses) | ~570K                       |
| Items transaccionales                      | ~1.8M                       |
| Familias de producto                       | 908                         |
| Reglas MBA generadas (todas)               | ~3,860                      |
| Reglas exclusivas por segmento             | ~1,516                      |
| Reglas accionables (1→1, 1→2)            | ~141                        |
| Vistas del dashboard                       | 7                           |
| Tests unitarios                            | 60+                         |
| Duración pipeline daily                   | ~30s                        |
| Duración pipeline weekly                  | ~45s                        |
| Cross-check temporalidad ↔ RFM            | **0.00% divergencia** |

### Distribución de segmentos (modelo v1)

| Segmento    |     % | Clientes | Descripción                                  |
| ----------- | ----: | -------: | --------------------------------------------- |
| Alto Valor  | 26.7% |    4,973 | Compras cada ~2 semanas, monetary moderado    |
| Hibernando  | 26.5% |    4,934 | Una compra histórica, cadencia >9 meses      |
| En Riesgo   | 18.7% |    3,479 | Eran activos, ahora con ratio >14 sin comprar |
| Ocasionales | 17.3% |    3,233 | Compras esparcidas, volumen bajo              |
| MVPs        | 10.8% |    2,019 | Compran cada ~4 días, alto monetary          |

---

## Decisiones técnicas

Estas son las decisiones de arquitectura que vale la pena entender si se va a mantener o extender el código.

### 1. CARGO100 se filtra en el runner

`CARGO100` es el cargo por pago con tarjeta de crédito que se registra como un item dentro de la orden pero **no es un producto**. Se filtra en `runner.py` ANTES de pasar items a cualquier módulo analítico. Una sola fuente de verdad.

### 2. Log-transform vive DENTRO del pipeline de sklearn

```python
Pipeline([
    ('log_transform', FunctionTransformer(np.log1p)),
    ('scaler', StandardScaler()),
    ('kmeans', KMeans(n_clusters=5, random_state=42)),
])
```

Encapsulamos el log-transform dentro del pipeline serializado. Sin esto, una versión preliminar tenía un bug donde MVPs absorbía el 92% de los clientes porque el log se aplicaba al entrenar pero no al predecir.

### 3. Timezone: parquets en UTC, agregados en CDMX

Los pedidos en MongoDB se guardan en UTC. La conversión a hora local CDMX se hace en `temporalidad.py` **antes** de extraer hora/día/mes. Sin esto, los heatmaps mostraban actividad nocturna ficticia.

### 4. Ratio de alertas defendido contra cadencia cero

```sql
recency::DOUBLE / GREATEST(dias_entre_compras, 1) AS ratio
```

Un cliente B2B real tiene 6,208 pedidos en 30 meses (~7 por día), cadencia mediana = 0. Sin el `GREATEST`, su ratio sería infinito.

### 5. Cuadrantes del Market Basket Opportunity Map: mediana dinámica

La división en cuadrantes (alto/bajo confidence × alto/bajo lift) usa la mediana de cada eje en las reglas mostradas. Esto garantiza división balanceada visualmente sin importar el filtro.

### 6. Ingest incremental con watermark

La primera corrida hace backfill completo. Las posteriores solo extraen pedidos con `fecha > watermark`. Sin esto, cada corrida re-extraería ~780K pedidos.

### 7. Quality checks automáticos

Validaciones en cada paso del runner. Ejemplos:

- Pedidos no pueden disminuir más de 1% entre corridas.
- Ningún cluster puede absorber más del 50% de la base.
- La suma de pedidos por segmento debe coincidir entre RFM y temporalidad (0% divergencia).

---

## Testing

El proyecto incluye **60+ tests unitarios** cubriendo cada módulo analítico y los componentes del pipeline.

```bash
# Correr todos los tests
uv run pytest

# Con reporte de cobertura
uv run pytest --cov=pulse --cov-report=html

# Solo un módulo
uv run pytest tests/test_mba.py

# Verbose
uv run pytest -v
```

Los tests cubren especialmente los **invariantes críticos**:

- El conteo de pedidos en orders coincide con el conteo en items.
- La distribución de segmentos suma 100%.
- Las reglas MBA cumplen los umbrales definidos.
- El cross-check temporalidad-RFM tiene 0% de divergencia.
- El modelo `v1` produce los mismos clusters dados los mismos inputs (reproducibilidad).

> [!IMPORTANT]
> Si modificas `mba.py`, `rfm.py` o `temporalidad.py`, **siempre corre los tests antes de mergear**. La mayoría de los bugs históricos del proyecto se detectaron por estos tests.

---

## Deployment a producción

Documentación completa: ver `8_documentacion_tecnica.qmd` en el portfolio o la guía completa más abajo.

### Resumen del deployment

1. **Servidor**: AlmaLinux 9.4 on-premise.
2. **SELinux**: modo permissive (registra violaciones sin bloquear).
3. **Firewall**: firewalld con puerto custom abierto.
4. **Supervisión**: systemd con `Restart=always`.
5. **Cron**: pipeline diario a las 3am.
6. **Acceso**: URL interna de la intranet, sin HTTPS (intranet corporativa).

### Servicio systemd (`/etc/systemd/system/pulse-dashboard.service`)

```ini
[Unit]
Description=Pulse Dashboard - FastAPI
After=network.target

[Service]
Type=simple
User=<usuario>
Group=<usuario>
WorkingDirectory=/home/<usuario>/ct-analytics
Environment="PATH=/home/<usuario>/.local/bin:/usr/local/bin:/usr/bin"
EnvironmentFile=/home/<usuario>/ct-analytics/.env
ExecStart=/home/<usuario>/.local/bin/uv run uvicorn pulse.dashboard.app:app --host 0.0.0.0 --port <PUERTO>
Restart=always
RestartSec=10
StandardOutput=append:/home/<usuario>/ct-analytics/logs/dashboard.log
StandardError=append:/home/<usuario>/ct-analytics/logs/dashboard.error.log

[Install]
WantedBy=multi-user.target
```

### Cron del pipeline diario 

```cron
0 3 * * * cd /home/<usuario>/ct-analytics && /home/<usuario>/.local/bin/uv run python -m pulse.pipeline daily --log-file logs/cron_$(date +\%Y\%m\%d).log 2>&1
```

### Test de robustez

Después del deployment, **reinicia el servidor**:

```bash
sudo reboot
```

Espera 1-2 minutos. Desde una máquina cliente, vuelve a entrar a `http://<IP>:<PUERTO>`. Si carga sin que hayas hecho nada en el servidor, el deployment es robusto.

---

## Operación diaria

```bash
# Estado del dashboard
sudo systemctl status pulse-dashboard

# Reiniciar el dashboard (por ejemplo después de un git pull)
sudo systemctl restart pulse-dashboard

# Ver logs en vivo
sudo journalctl -u pulse-dashboard -f

# Correr pipeline manualmente (sin esperar al cron)
cd /home/<usuario>/ct-analytics
uv run python -m pulse.pipeline daily

# Forzar recálculo completo (incluyendo MBA)
uv run python -m pulse.pipeline weekly

# Actualizar código desde git
cd /home/<usuario>/ct-analytics
git pull
sudo systemctl restart pulse-dashboard

# Ver corridas recientes del cron
ls -lt logs/cron_*.log | head -5
```

### Troubleshooting

| Síntoma                               | Causa probable                   | Solución                                               |
| -------------------------------------- | -------------------------------- | ------------------------------------------------------- |
| `No module named pulse.pipeline`     | Paquete no instalado en venv     | `uv sync` con `pyproject.toml` correcto             |
| Permission denied al subir archivos    | Owner es root, no usuario        | `sudo chown -R user:user .`                           |
| `Address already in use` al arrancar | Proceso anterior tomó el puerto | `sudo ss -tlnp \| grep <PUERTO>` y `sudo kill <PID>` |
| Dashboard responde 500                 | Parquets faltantes o corruptos   | Re-correr `uv run python -m pulse.pipeline weekly`    |
| Pipeline falla en MongoDB              | Credenciales o red               | Verificar `.env` y `nc -zv <host> 27017`            |
| Servicio crashea en bucle              | Error en código o config        | `sudo journalctl -u pulse-dashboard -n 100`           |

---

## Documentación adicional

El portfolio público en [anmerino-pnd.github.io/ct-analytics](https://anmerino-pnd.github.io/ct-analytics/0_home.html) documenta el proyecto en profundidad:

1. **Inicio** — Resumen ejecutivo
2. **Comprensión del negocio** — Objetivos y alcance
3. **Exploración de datos** — Hallazgos del EDA
4. **Análisis RFM** — Cadencia personalizada, ratio de urgencia
5. **Segmentación** — Selección de k=5, perfilamiento de clusters
6. **Market Basket Analysis** — Opportunity Map con cuadrantes
7. **Estacionalidad** — Patrones temporales por segmento
8. **De Investigación a Producción** — MLOps, pipeline ETL, dashboard
9. **Documentación Técnica** — Instalación, operación, troubleshooting
10. **Visión y Futuro** — Roadmap

---

## Roadmap

### Iteración inmediata

- [ ] Sesión de validación con marketing (30-45 min) y aplicación de feedback.
- [ ] CI/CD con GitHub Actions (pytest + linter automático en cada push).
- [ ] Drift monitoring con alertas activas (hoy solo se registra en log).

### Mediano plazo

- [ ] **Forecasting** de pedidos por segmento con Prophet o LightGBM.
- [ ] **Customer Lifetime Value (CLV)** predictivo (BG/NBD + Gamma-Gamma).
- [ ] **API de recomendación** en tiempo real integrada al portal B2B.
- [ ] **MLFlow** para tracking de experimentos cuando haya múltiples modelos en juego.

---

## Autores

| Nombre                         | Rol                              | Contacto                                                                 |
| ------------------------------ | -------------------------------- | ------------------------------------------------------------------------ |
| **Angel Merino Cedeño** | Data Scientist / Líder técnico | [LinkedIn](https://www.linkedin.com/in/anmerino-pnd) · acedeno00@gmail.com |
| Gerardo Leyva Conde            | Colaborador                      | —                                                                       |
| Roberto Navarro Bartolini      | Colaborador                      | —                                                                       |
| Abraham Rojo Salazar           | Colaborador                      | —                                                                       |

---

## Licencia

Proyecto propietario de CT Internacional. Este repositorio contiene código de uso interno; los datos transaccionales no están incluidos. El portfolio público asociado utiliza datos escalados o anonimizados y claves de productos ofuscadas para preservar la confidencialidad operativa.

---

<div align="center">

**Construido con rigor técnico y enfoque en productización.**

*De notebook exploratorio a servicio operativo en 4 fases.*

[⬆ Volver arriba](#pulse--customer-analytics-platform)

</div>
