# TaarYa — Packaging Guide

> How to distribute, install, and integrate TaarYa with the broader astronomy software ecosystem.

---

## 1. Installation Options

### Option A — pip (Simplest)

```bash
pip install taarya
```

The `taarya` package is registered on PyPI and installs all dependencies automatically.

**With optional extras:**
```bash
pip install taarya[desktop]        # includes pywebview for desktop GUI
pip install taarya[dev]           # includes pytest, ruff, mypy, pre-commit
pip install taarya[all]           # everything
```

**Verify installation:**
```bash
taarya-readiness
taarya-server
```

---

### Option B — conda / mamba

```bash
# Install from conda-forge (after submission)
conda install -c conda-forge taarya

# Or with mamba (faster resolver)
mamba install -c conda-forge taarya
```

**Create a reproducible environment:**
```bash
mamba env create -f conda-lock.yml
conda activate taarya
```

The `feedstocks/taarya/recipe/meta.yaml` is the conda-forge submission template. To submit:
1. Fork https://github.com/conda-forge/taarya-feedstock
2. Update `recipe/meta.yaml` with the new version + sha256
3. Open a PR; conda-forge bots auto-update on merge

---

### Option C — Docker (Zero-Config)

```bash
# One-command full stack (requires Docker + Docker Compose)
docker compose up --build

# Open the dashboard
open http://localhost:8000
```

**With GPU support (MESA workloads):**
```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

**Just the app container (backends already running elsewhere):**
```bash
docker run -it \
  -e DATABASE_URL="postgresql://taarya:taarya123@host.docker.internal:5432/astronomy" \
  -e QDRANT_HOST=host.docker.internal \
  -e NEO4J_URI="bolt://host.docker.internal:7687" \
  -p 8000:8000 \
  ghcr.io/hmblecreator/taarya:latest
```

---

### Option D — Development Install

```bash
git clone https://github.com/HmbleCreator/TaarYa.git
cd TaarYa
uv sync                  # fast, uses uv
# or: pip install -e ".[all]"
```

---

## 2. Backend Setup (PostgreSQL + Q3C, Qdrant, Neo4j)

TaarYa requires three external services. The fastest way to get them running:

### Automated (recommended)

```bash
docker compose up -d postgres qdrant neo4j
```

### Manual

| Service | Install | Notes |
|---|---|---|
| **PostgreSQL 16** | `apt install postgresql-16` | Must have `pg_trgm` + Q3C extension |
| **Q3C extension** | Build from [segasai/q3c](https://github.com/segasai/q3c) | `CREATE EXTENSION q3c;` |
| **Qdrant** | `pip install qdrant-client` or Docker | Version ≥ 1.7 |
| **Neo4j 5** | `brew install neo4j` or Docker | Community edition |

**Q3C PostgreSQL setup:**
```sql
-- In postgres shell: psql -U postgres -d astronomy
CREATE EXTENSION IF NOT EXISTS q3c;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

---

## 3. Astronomy Software Integrations

TaarYa ships three optional integration modules for the broader astronomy toolchain:

### 3a. MESA (Stellar Evolution)

**What it does:** Exports any TaarYa star/candidate as a MESA inlist — ready to simulate with [MESA](https://mesastar.org/).

**Integration points:**

| File | Purpose |
|---|---|
| `src/extensions/taarya_mesa.py` | Inlist generator, mass estimation from HR-diagram position |
| `src/api/scientific.py` → `GET /api/mesa/inlist/{source_id}` | REST endpoint |
| `src/api/scientific.py` → `GET /api/mesa/physical-params/{source_id}` | Mass/age estimates |
| `src/api/scientific.py` → `GET /api/mesa/cluster/{name}` | Cluster averaged inlist |

**MESA installation:**
```bash
# Download MESA from https://mesastar.org/ (requires registration)
tar xzf mesa_r23_08_01.tar.gz
export MESA_DIR=$PWD/mesa
export OMP_NUM_THREADS=8
./star/test_suite/run_star_extras
```

**TaarYa → MESA workflow:**
```
TaarYa discovery candidate (source_id, ra, dec, G, BP-RP, parallax)
  → /api/mesa/physical-params/{source_id}   [estimate mass, age, Z]
  → /api/mesa/inlist/{source_id}           [download .inlist]
  → MESA SDK: $MESA_DIR/star/test_suite/run_star_extras
```

**Package MESA integration for conda:**
```yaml
# In meta.yaml, add:
run:
  - mesastar >= 23.08
```

---

### 3b. SAOImage DS9 (Image Visualization)

**What it does:** Programmatic DS9 control via XPA messaging — pan to coordinates, load FITS cutouts, overlay discovery candidates.

**Integration points:**

| File | Purpose |
|---|---|
| `src/extensions/taarya_ds9.py` | XPA command executor |
| `src/api/scientific.py` → `GET /api/interop/ds9-load` | Load FITS + overlay stars |
| `src/api/scientific.py` → `GET /api/interop/aladin-link` | Aladin Lite sky overlay |

**DS9 installation:**
```bash
# Linux
apt install saods9
# macOS
brew install saods9
# Windows: ds9 available via WSL/X11 or pre-built binary
```

**XPA tools installation (required):**
```bash
apt install xpa-tools     # Linux
brew install xpa-tools     # macOS
```

**TaarYa → DS9 workflow:**
```
TaarYa cone search → [ra, dec, radius_deg]
  → /api/interop/ds9-load  [POST star list]
  → DS9 XPA: xpaset ds9 regions command ... [overlaid circles]
  → DS9 XPA: xpaset ds9 file ... [FITS cutout from Aladdin/IRSA]
```

**DS9 availability check (in Python):**
```python
from src.extensions.taarya_ds9 import TaarYaDS9
ds9 = TaarYaDS9()
if ds9.is_ds9_running():
    ds9.point_at_sky(66.75, 15.87)  # Pan to Hyades
else:
    print("DS9 not available — install saods9 and xpa-tools")
```

---

### 3c. CASA (Radio Interferometry)

**What it does:** Cross-match TaarYa stellar candidates with CASA visibility data, generate CRTF sky regions.

**Integration points:**

| File | Purpose |
|---|---|
| `src/extensions/taarya_casa.py` | MS cross-match, CRTF generation |
| `src/api/scientific.py` → `GET /api/interop/ds9-regions` | DS9 region file output |

**CASA installation:**
```bash
# CASA is distributed as a binary — download from NRAO
# https://casadocs.readthedocs.io/en/stable/notebooks/
# Registration required, ~5GB download

# After installation
export CASAPATH=/path/to/casa-6.5.0
$cASAPATH/bin/casa --version
```

**TaarYa → CASA workflow:**
```python
from src.extensions.taarya_casa import TaarYaCASA
casa = TaarYaCASA(casa_path="/path/to/casa")
# Generate CRTF region file for TaarYa candidates
casa.to_crtf(taarya_candidates[:5], "hyades_candidates.crtf")
```

**Package CASA integration:**
```yaml
# In meta.yaml, add:
run:
  - casa >= 6.5
  # CASA is not conda-installable — document manual install requirement
```

---

## 4. PyPI Release Checklist

To publish `taarya` to PyPI:

### 1. Pre-release audit
```bash
# Run full regression
python scripts/run_regression.py --full

# Check package structure
pip install build twine
python -m build
twine check dist/*
```

### 2. Tag and release
```bash
# Update version in pyproject.toml → commit → tag
git tag -a v1.0.0 -m "TaarYa v1.0.0 — ADASS XXXVI submission"
git push origin main --tags
```

### 3. Publish to PyPI
```bash
# Test PyPI first (TestPyPI)
twine upload --repository testpypi dist/*

# Then production PyPI
twine upload dist/*
```

### 4. GitHub Actions automation (recommended)
```yaml
# .github/workflows/publish.yml
- name: Publish to PyPI
  if: startsWith(github.ref, 'refs/tags/v')
  uses: pypa/gh-action-pypi-publish@release/v1
  with:
    password: ${{ secrets.PYPI_API_TOKEN }}
```

---

## 5. Docker Registry Publishing

```bash
# Build multi-architecture images
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t ghcr.io/hmblecreator/taarya:1.0.0 \
  -t ghcr.io/hmblecreator/taarya:latest \
  --push \
  -f Dockerfile .

# Verify
docker run -d -p 8000:8000 ghcr.io/hmblecreator/taarya:latest
curl http://localhost:8000/health
```

---

## 6. Astroconda / STScI Integration

For institutional astronomy environments (STScI, ESO, NRAO):

```bash
# Install via astroconda channel (after conda-forge submission)
conda install -c astroconda taarya
```

The STScI environment already includes `astropy`, `astroquery`, and `specutils` — TaarYa extends these for discovery support.

---

## 7. HPC / SLURM Deployment

For running TaarYa on shared HPC clusters:

```bash
#!/bin/bash
#SBATCH --job-name=taarya
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=4
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --partition=compute
#SBATCH --output=taarya_%j.out

module load Python/3.12
module load PostgreSQL/16
module load gcc/13

# Start backends (if not pre-running)
srun --ntasks=1 dockerd &   # only if Docker available
sleep 10

# Run TaarYa server
srun python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

---

## 8. Quick-Start for Astronomers

```bash
# 1. Install (pick one)
pip install taarya                    # pip
conda install -c conda-forge taarya   # conda (after feedstocks published)

# 2. Start backends
docker compose up -d postgres qdrant neo4j

# 3. Ingest papers
taarya-corpus --target 5000

# 4. Start server
taarya-server

# 5. Open browser
open http://localhost:8000
```
