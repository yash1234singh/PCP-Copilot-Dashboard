#!/bin/bash

# Start Docker containers and continuously collect logs
# This script starts the containers and runs log collection in the background

echo "=== Starting PCP Monitoring Stack with Log Collection ==="

# Start containers
echo "Starting Docker containers..."
docker-compose up -d

# Wait for containers to initialize
echo "Waiting for containers to start..."
sleep 5

# Run initial log collection
echo "Collecting initial logs..."
./collect_logs.sh

# Start continuous log collection in background
echo "Starting continuous log collection (every 30 seconds)..."
(
    while true; do
        sleep 30
        ./collect_logs.sh > /dev/null 2>&1
    done
) &

LOG_COLLECTOR_PID=$!
echo "Log collector running with PID: ${LOG_COLLECTOR_PID}"
echo "To stop log collection: kill ${LOG_COLLECTOR_PID}"
echo ""
echo "=== Stack Started Successfully ==="
echo "Grafana: http://localhost:3000 (admin/admin)"
echo "InfluxDB: http://localhost:8086"
echo "Logs: ./HOST_SHARE/logs/container_logs/"
echo ""
echo "To stop everything: docker-compose down && kill ${LOG_COLLECTOR_PID}"
