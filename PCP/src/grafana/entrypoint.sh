#!/bin/bash
set -e

# Read token from mounted file
if [ -f /admin_token ]; then
  echo "Reading InfluxDB token from /admin_token..."
  # Extract token from JSON file
  INFLUXDB_TOKEN=$(grep -o '"token": *"[^"]*"' /admin_token | sed 's/"token": *"\([^"]*\)"/\1/')

  if [ -n "$INFLUXDB_TOKEN" ]; then
    echo "✓ Token loaded successfully"
    export INFLUXDB_TOKEN

    # Generate datasource configuration with token
    cat > /etc/grafana/provisioning/datasources/influxdb3.yml <<EOF
apiVersion: 1

datasources:
  - name: InfluxDB3
    type: influxdb
    uid: influxdb3-sql
    access: proxy
    url: http://influxdb3-core:8181
    user:
    password:
    database: pcp-metrics
    basicAuth: false
    isDefault: true
    jsonData:
      httpMode: POST
      version: SQL
      dbName: pcp-metrics
      tlsSkipVerify: true
      tlsAuthWithCACert: false
      httpHeaderName1: Authorization
    secureJsonData:
      token: ${INFLUXDB_TOKEN}
      httpHeaderValue1: Bearer ${INFLUXDB_TOKEN}
    version: 1
    editable: true
EOF
    echo "✓ Datasource configuration generated"
  else
    echo "✗ Failed to extract token from /admin_token"
    exit 1
  fi
else
  echo "✗ /admin_token file not found"
  exit 1
fi

# Start Grafana
echo "Starting Grafana..."
exec /run.sh "$@"
