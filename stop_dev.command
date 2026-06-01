#!/bin/bash
# Double-click to stop the LeadGen dev stack.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
else
  COMPOSE="docker-compose"
fi

echo "==> Stopping LeadGen stack"
$COMPOSE down

echo ""
echo "✅ Stopped. Data is preserved in the postgres_data volume."
echo "   To wipe data too:  $COMPOSE down -v"
echo ""
read -n 1 -p "Press any key to close..."
