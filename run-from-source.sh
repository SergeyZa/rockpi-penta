#!/bin/bash
# Run rockpi-penta directly from source checkout for testing.
# Usage: sudo ./run-from-source.sh [env-file]
#   env-file defaults to rpi5.env

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/rockpi-penta/usr/bin/rockpi-penta"
ENV_DIR="$APP_DIR/env"

ENV_FILE="${1:-rpi5.env}"
ENV_PATH="$ENV_DIR/$ENV_FILE"

if [ ! -f "$ENV_PATH" ]; then
    echo "Error: env file not found: $ENV_PATH"
    echo "Available env files:"
    ls "$ENV_DIR"
    exit 1
fi

echo "Loading environment from: $ENV_FILE"
set -a
. "$ENV_PATH"
set +a

echo "Checking gpiod python module..."
python3 -c "import gpiod; print('gpiod version:', gpiod.__version__)"

echo "Starting rockpi-penta from source..."
cd "$APP_DIR"
exec python3 main.py
