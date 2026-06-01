#!/bin/bash
# Double-click to start the LeadGen dev stack (Postgres + Redis + API + Celery worker + beat).
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==> Working dir: $SCRIPT_DIR"

# 1. Docker check
if ! command -v docker >/dev/null 2>&1; then
  echo "❌ Docker is not installed. Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
  read -n 1 -p "Press any key to close..."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "==> Docker daemon isn't running. Launching Docker Desktop..."
  open -a Docker || true
  echo -n "    Waiting for Docker to start"
  for i in {1..60}; do
    if docker info >/dev/null 2>&1; then echo " ✓"; break; fi
    echo -n "."
    sleep 2
  done
  if ! docker info >/dev/null 2>&1; then
    echo ""
    echo "❌ Docker didn't start in time. Open Docker Desktop manually, then re-run this script."
    read -n 1 -p "Press any key to close..."
    exit 1
  fi
fi

# 2. .env check
if [ ! -f .env ]; then
  echo "==> No .env file found, copying .env.example"
  cp .env.example .env
fi

# 3. Pick compose command (v2 plugin vs legacy)
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
else
  COMPOSE="docker-compose"
fi

# 4. Build + start
echo "==> Building images (first run takes a few minutes — Playwright + Chromium)"
$COMPOSE build

echo "==> Running database migrations"
$COMPOSE run --rm api alembic upgrade head || echo "    (migrations skipped or already applied)"

echo "==> Starting stack in the background"
$COMPOSE up -d

echo ""
echo "==> Service status:"
$COMPOSE ps

echo ""
echo "✅ Stack is up."
echo "   API:        http://localhost:8000"
echo "   API docs:   http://localhost:8000/docs"
echo "   Health:     http://localhost:8000/health"
echo "   Postgres:   localhost:5432  (leadgen/leadgen/leadgen)"
echo "   Redis:      localhost:6379"
echo ""
echo "   Tail logs:  cd \"$SCRIPT_DIR\" && $COMPOSE logs -f"
echo "   Stop:       double-click stop_dev.command"
echo ""
read -n 1 -p "Press any key to close this window..."
