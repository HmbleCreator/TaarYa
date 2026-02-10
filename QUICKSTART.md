# Quick Start Guide

## 1. Start Docker Databases

```bash
cd c:\Users\amiku\Downloads\8th_Sem\TaarYa
docker-compose up -d
```

Wait 30 seconds for services to start. Verify with:
```bash
docker-compose ps
```

## 2. Setup Python Environment

```bash
# Copy environment file
copy .env.example .env

# Create virtual environment and install dependencies with uv
uv venv
uv pip install -r requirements.txt
# OR if using uv specific lock file in future: uv sync
```

## 3. Initialize Database

```bash
python -m src.init_db
```

This will create the Q3C extension and all tables.

## 4. Run Tests

```bash
python -m tests.test_ingestion
```

Should show all tests passing ✅

## 5. Ingest Sample Gaia Data

Download a sample from: https://gea.esac.esa.int/archive/

Then run:
```bash
python -m src.ingestion.gaia_ingestor path\to\gaia_sample.csv 10000
```

## 6. Start the API

```bash
python -m src.main
```

Visit: http://localhost:8000/docs

---

**Troubleshooting:**

- **Q3C errors**: Make sure PostgreSQL container finished initialization
- **Connection refused**: Run `docker-compose ps` to check services
- **Import errors**: Activate venv and reinstall requirements
