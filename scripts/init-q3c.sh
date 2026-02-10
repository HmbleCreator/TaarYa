#!/bin/bash
set -e

# This script installs the Q3C extension for spatial indexing
# Q3C enables efficient cone searches on spherical coordinates

echo "Installing Q3C extension..."

# Install build dependencies
apk add --no-cache --virtual .build-deps \
    gcc \
    make \
    postgresql-dev \
    git

# Clone and build Q3C
cd /tmp
git clone https://github.com/segasai/q3c.git
cd q3c
make
make install

# Clean up
cd /
rm -rf /tmp/q3c
apk del .build-deps

echo "Q3C extension installed successfully"

# Create the extension in the database (will run when DB starts)
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS q3c;
EOSQL

echo "Q3C extension enabled in database"
