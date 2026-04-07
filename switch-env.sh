#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ENV="${1:-}"

if [[ "$ENV" != "dev" && "$ENV" != "prod" ]]; then
  echo "Usage: ./switch-env.sh <dev|prod>"
  echo ""
  echo "Current config:"
  grep api_base_url "$DIR/config.json" | sed 's/.*: *"/  /' | sed 's/".*//'
  exit 1
fi

cp "$DIR/config.$ENV.json" "$DIR/config.json"
echo "Switched to $ENV"
grep api_base_url "$DIR/config.json" | sed 's/.*: *"/  /' | sed 's/".*//'
