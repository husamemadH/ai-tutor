#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p dist
out="dist/ai_tutor_data.sql.gz"

docker compose exec -T db pg_dump \
  -U ai_tutor -d ai_tutor \
  --data-only --no-owner --no-privileges \
  --table=public.books --table=public.chunks \
  | gzip -9 > "$out"

echo "wrote $out ($(du -h "$out" | cut -f1))"
