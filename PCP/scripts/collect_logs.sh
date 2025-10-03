#!/bin/bash

# Script to collect Docker container logs to src/logs directory
# Each container logs are saved in their own subdirectory with simple names

BASE_LOG_DIR="../src/logs"

echo "=== Docker Container Log Collection ==="
echo "Timestamp: $(date)"
echo ""

# Get list of containers
CONTAINERS=("influxdb" "grafana" "pcp_parser")

for container in "${CONTAINERS[@]}"; do
    echo "Collecting logs from ${container}..."

    # Create container-specific log directory
    LOG_DIR="${BASE_LOG_DIR}/${container}"
    mkdir -p "${LOG_DIR}"

    # Check if container exists
    if docker ps -a --format '{{.Names}}' | grep -q "^${container}$"; then
        # Write logs to simple filename (appends if exists)
        docker logs "${container}" > "${LOG_DIR}/${container}.log" 2>&1
        echo "  ✓ Saved to ${LOG_DIR}/${container}.log"
    else
        echo "  ✗ Container ${container} not found"
    fi
done

echo ""
echo "=== Log Collection Complete ==="
echo "Logs saved to: ${BASE_LOG_DIR}/"
echo ""

# Show log files
echo "Log files:"
for container in "${CONTAINERS[@]}"; do
    LOG_FILE="${BASE_LOG_DIR}/${container}/${container}.log"
    if [ -f "${LOG_FILE}" ]; then
        SIZE=$(ls -lh "${LOG_FILE}" | awk '{print $5}')
        echo "  ${container}.log (${SIZE})"
    fi
done
