#!/bin/bash
# Helper script to display the InfluxDB admin token for Explorer UI setup

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../src/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "Error: .env file not found at $ENV_FILE"
    echo "Run 'docker-compose up -d' first to generate the token"
    exit 1
fi

TOKEN=$(grep "^INFLUXDB_TOKEN=" "$ENV_FILE" | cut -d'=' -f2)

if [ -z "$TOKEN" ]; then
    echo "Error: INFLUXDB_TOKEN not found in .env file"
    echo "Run 'docker-compose up -d' first to generate the token"
    exit 1
fi

echo "=========================================="
echo "InfluxDB 3 Explorer Configuration"
echo "=========================================="
echo ""
echo "Server Name:  influxdb3-server"
echo "Server URL:   http://host.docker.internal:8181"
echo "Token:        $TOKEN"
echo ""
echo "=========================================="
echo "Copy the token above and paste it into"
echo "the Explorer UI at http://localhost:8888"
echo "=========================================="
