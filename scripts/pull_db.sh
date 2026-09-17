#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
tag="${1:-db-data}"

uv run ai-tutor init-db

docker compose exec -T db psql -v ON_ERROR_STOP=1 -U ai_tutor -d ai_tutor \
  -c "DELETE FROM chunks;" -c "DELETE FROM books;"

gh release download "$tag" -p ai_tutor_data.sql.gz -O - --clobber \
  | gunzip \
  | docker compose exec -T db psql -v ON_ERROR_STOP=1 -U ai_tutor -d ai_tutor

echo "restored books + chunks from release '$tag'"
