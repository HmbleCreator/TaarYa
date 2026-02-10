# TaarYa Setup Guide

## Prerequisites
- Docker Desktop (for Windows)
- Python 3.9+
- Git

## Quick Start

### 1. Clone and Setup Environment
```bash
# Copy environment template
copy .env.example .env

# Edit .env and add your OpenAI API key (or configure Ollama)
```

### 2. Start Database Services
```bash
docker-compose up -d
```

This will start:
- **Qdrant** (Vector DB) on port 6333
- **Neo4j** (Graph DB) on ports 7474 (HTTP) and 7687 (Bolt)
- **PostgreSQL** (Spatial DB) on port 5432

### 3. Install Python Dependencies
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Run the Application
```bash
python -m src.main
```

The API will be available at `http://localhost:8000`

## Verify Installation

### Check Docker Services
```bash
docker-compose ps
```

All three services should show as "Up".

### Access Web Interfaces
- **Neo4j Browser**: http://localhost:7474 (user: neo4j, password: taarya123)
- **API Docs**: http://localhost:8000/docs

## Next Steps
- Configure your LLM provider in `.env`
- Start ingesting data (see ingestion guide)
- Explore the API documentation
