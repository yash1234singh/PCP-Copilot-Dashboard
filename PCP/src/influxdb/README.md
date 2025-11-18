# InfluxDB 3 Core Configuration

This directory contains InfluxDB 3 Core configuration files and documentation.

## ⚠️ Important: Migration to InfluxDB 3 Core

This project uses **InfluxDB 3 Core**, not InfluxDB v2. Key differences:

| Feature | InfluxDB v2 | InfluxDB 3 Core |
|---------|-------------|-----------------|
| **Web UI** | ✅ Available | ❌ API-only |
| **Query Language** | Flux | SQL |
| **Authentication** | Username/Password + Token | Token-only (via CLI) |
| **Structure** | Organizations → Buckets | Databases |
| **Port** | 8086 | 8181 |
| **Configuration** | UI + Environment vars | CLI + Environment vars |

## Structure

```
influxdb/
├── config/         # Custom InfluxDB configuration files (currently unused)
├── init-scripts/   # Initialization scripts (currently unused)
├── logs/           # Mounted log directory (from docker-compose.yml)
└── README.md       # This file
```

## Current Configuration

InfluxDB 3 Core is configured through environment variables in `docker-compose.yml`:

```yaml
influxdb3-core:
  image: influxdb:3-core
  container_name: influxdb3-core
  ports:
    - "8181:8181"
  volumes:
    - influxdb-data:/var/lib/influxdb3
    - ./logs/influxdb:/logs
  command:
    - influxdb3
    - serve
    - --node-id=${INFLUXDB_NODE_ID:-node1}
    - --object-store=file
    - --data-dir=/var/lib/influxdb3
  environment:
    - INFLUXDB_TOKEN=${INFLUXDB_TOKEN:-pcp-admin-token-12345}
    - INFLUXDB_NODE_ID=${INFLUXDB_NODE_ID:-node1}
    - RUST_LOG=info
```

**Key Settings:**
- `INFLUXDB_TOKEN`: Admin token (generated via CLI, stored in `.env`)
- `INFLUXDB_NODE_ID`: Node identifier for clustering (default: `node1`)
- `--object-store=file`: Use local file storage
- `--data-dir=/var/lib/influxdb3`: Data directory location

## Initial Setup

### Step 1: Start InfluxDB 3 Core

```bash
cd src
docker-compose up -d influxdb3-core
```

Wait for the container to be healthy (~10 seconds):

```bash
docker-compose ps influxdb3-core
# Should show: Up X seconds (healthy)
```

### Step 2: Generate Admin Token

InfluxDB 3 Core requires a token generated via CLI:

```bash
docker-compose exec influxdb3-core influxdb3 create token --admin
```

**Output:**
```
New token created successfully!

Token: apiv3_IyUcK8d9lp18tedgDD87424P1SmX12klDvOMqxgcPbJXeoY_GVVyqTdjZmHx7DgBDp2X0Jm1m6Z4XHfN6DNmSg
HTTP Requests Header: Authorization: Bearer apiv3_IyUcK8d9lp18tedgDD87424P1SmX12klDvOMqxgcPbJXeoY_GVVyqTdjZmHx7DgBDp2X0Jm1m6Z4XHfN6DNmSg

IMPORTANT: Store this token securely, as it will not be shown again.
```

**Important Notes:**
- Token is stored in InfluxDB's catalog (persistent)
- Only generate once per InfluxDB instance
- Token persists across container restarts
- Only recreate if data volume is deleted

### Step 3: Update .env File

Copy the generated token to your `.env` file:

```bash
# Edit src/.env and update the INFLUXDB_TOKEN line:
INFLUXDB_TOKEN=apiv3_IyUcK8d9lp18tedgDD87424P1SmX12klDvOMqxgcPbJXeoY_GVVyqTdjZmHx7DgBDp2X0Jm1m6Z4XHfN6DNmSg
```

### Step 4: Restart Services

Restart services that use the token:

```bash
docker-compose restart pcp_parser_python grafana
```

## Data Storage

Data is stored in a Docker volume: `influxdb-data`

This volume persists:
- Database files (object store)
- Catalog metadata
- Indexes
- WAL (Write-Ahead Log)
- Admin tokens

**Volume location:**
```bash
# Check volume details
docker volume inspect influxdb-data

# Check data directory size
docker-compose exec influxdb3-core du -sh /var/lib/influxdb3
```

## Database Management

### Create Database (Optional)

InfluxDB 3 Core automatically creates databases on first write. Manual creation:

```bash
docker-compose exec influxdb3-core influxdb3 database create pcp-metrics
```

### List Databases

```bash
docker-compose exec influxdb3-core influxdb3 database list
```

### Delete Database

```bash
docker-compose exec influxdb3-core influxdb3 database delete pcp-metrics
```

## Access

**⚠️ No Web UI Available** - InfluxDB 3 Core is API-only

- **Health Endpoint**: http://localhost:8181/health (no auth required, returns plain text "OK")
- **Write API**: http://localhost:8181/api/v2/write (v2-compatible)
- **Query API**: http://localhost:8181/api/v3/query_sql (SQL queries)
- **Database**: `pcp-metrics`
- **Token**: From `.env` file

### API Examples

**Health Check:**
```bash
curl http://localhost:8181/health
# Returns: OK
```

**Write Data (Line Protocol):**
```bash
curl -X POST "http://localhost:8181/api/v2/write?bucket=pcp-metrics" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: text/plain" \
  --data-raw "test_metric,host=testhost value=123.45 $(date +%s)000000000"
```

**Query Data (SQL):**
```bash
curl -X POST "http://localhost:8181/api/v3/query_sql" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "db": "pcp-metrics",
    "q": "SELECT * FROM test_metric LIMIT 10"
  }'
```

## Querying Data

InfluxDB 3 Core uses **SQL** (not Flux). Example queries:

### Count Data Points

```bash
curl -X POST "http://localhost:8181/api/v3/query_sql" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "db": "pcp-metrics",
    "q": "SELECT COUNT(*) FROM pcp_metrics"
  }'
```

### Query Recent Data

```bash
curl -X POST "http://localhost:8181/api/v3/query_sql" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "db": "pcp-metrics",
    "q": "SELECT * FROM pcp_metrics WHERE time > now() - INTERVAL '\''1 hour'\''"
  }'
```

### Filter by Tags

```bash
curl -X POST "http://localhost:8181/api/v3/query_sql" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "db": "pcp-metrics",
    "q": "SELECT * FROM pcp_metrics WHERE product_type = '\''SERVER1'\''"
  }'
```

## Monitoring

### Check Service Status

```bash
# Container status
docker-compose ps influxdb3-core

# Resource usage
docker stats influxdb3-core

# Recent logs
docker-compose logs --tail=100 influxdb3-core

# Follow logs
docker-compose logs -f influxdb3-core
```

### Check Data Storage

```bash
# Check volume size
docker volume inspect influxdb-data

# Check data directory inside container
docker-compose exec influxdb3-core du -sh /var/lib/influxdb3

# List files in data directory
docker-compose exec influxdb3-core ls -la /var/lib/influxdb3
```

## Troubleshooting

### Issue: Container Won't Start

**Symptoms:**
```
Error: failed to start container
```

**Solution:**
```bash
# Check logs
docker-compose logs influxdb3-core

# Remove old volumes if migrating from v2
docker-compose down -v
docker volume rm influxdb-data

# Start fresh
docker-compose up -d influxdb3-core
```

### Issue: "Database not found"

**Symptoms:**
```
Error: database 'pcp-metrics' not found
```

**Solution:**

InfluxDB 3 creates databases automatically on first write. Just start writing data:

```bash
# Test write
curl -X POST "http://localhost:8181/api/v2/write?bucket=pcp-metrics" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: text/plain" \
  --data-raw "test,host=test value=1 $(date +%s)000000000"

# Or start the parser (will create database on first write)
docker-compose up -d pcp_parser_python
```

### Issue: Authentication Errors

**Symptoms:**
```
Error: unauthorized
Error: cannot authenticate token e=InvalidToken
```

**Solution:**

1. **Generate a new admin token:**
   ```bash
   cd src
   docker-compose exec influxdb3-core influxdb3 create token --admin
   ```

2. **Update `.env` file:**
   ```bash
   # Edit src/.env
   INFLUXDB_TOKEN=apiv3_YOUR_NEW_TOKEN_HERE
   ```

3. **Restart services:**
   ```bash
   docker-compose restart pcp_parser_python grafana
   ```

4. **Verify token is loaded:**
   ```bash
   docker-compose exec pcp_parser_python env | grep INFLUXDB_TOKEN
   ```

### Issue: Healthcheck Failing

**Symptoms:**
```
docker-compose ps shows "unhealthy"
```

**Solution:**
```bash
# Test health endpoint manually
curl http://localhost:8181/health

# If it returns "OK", restart the service
docker-compose restart influxdb3-core

# If it fails, check logs
docker-compose logs influxdb3-core
```

### Issue: MissingToken Errors in Logs

**Symptoms:**
```
cannot authenticate token e=MissingToken
```

**Explanation:**

This is **normal** and can be ignored. The healthcheck uses a process check (not HTTP endpoint authentication).

**Why it happens:**
- InfluxDB 3 Core logs all requests, including healthchecks
- Healthchecks don't include auth tokens
- These log messages don't indicate a problem

**Action:** No action needed - these are informational logs only.

## Maintenance

### Backup Data

```bash
# Stop container
docker-compose stop influxdb3-core

# Backup data volume
docker run --rm -v influxdb-data:/data -v $(pwd):/backup \
  ubuntu tar czf /backup/influxdb-backup-$(date +%Y%m%d).tar.gz /data

# Start container
docker-compose start influxdb3-core
```

### Restore Data

```bash
# Stop container
docker-compose stop influxdb3-core

# Restore data volume
docker run --rm -v influxdb-data:/data -v $(pwd):/backup \
  ubuntu tar xzf /backup/influxdb-backup-YYYYMMDD.tar.gz -C /

# Start container
docker-compose start influxdb3-core
```

### Clean Up Old Data

InfluxDB 3 Core does not have built-in retention policies yet. Manual cleanup:

```bash
# Delete old data (SQL)
curl -X POST "http://localhost:8181/api/v3/query_sql" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "db": "pcp-metrics",
    "q": "DELETE FROM pcp_metrics WHERE time < now() - INTERVAL '\''30 days'\''"
  }'
```

### Reset Everything

```bash
# Stop and remove everything
docker-compose down -v

# Remove data volume
docker volume rm influxdb-data

# Start fresh
docker-compose up -d influxdb3-core

# Generate new token (required after volume deletion)
docker-compose exec influxdb3-core influxdb3 create token --admin

# Update .env with new token
```

## API Endpoints Reference

| Endpoint | Method | Purpose | Auth Required |
|----------|--------|---------|---------------|
| `/health` | GET | Health check | No |
| `/api/v2/write` | POST | Write line protocol | Yes (Bearer token) |
| `/api/v3/write_lp` | POST | Write line protocol (v3 native) | Yes |
| `/api/v3/query_sql` | POST | Query with SQL | Yes |

## Environment Variables

InfluxDB 3 Core reads these from `docker-compose.yml`:

```yaml
environment:
  - INFLUXDB_TOKEN=pcp-admin-token-12345  # Admin token
  - INFLUXDB_NODE_ID=node1                # Cluster node ID
```

These are set from the `.env` file with defaults.

## Migration from InfluxDB v2

If migrating from InfluxDB v2:

1. **Stop all services:**
   ```bash
   docker-compose down
   ```

2. **Remove old InfluxDB v2 volume:**
   ```bash
   docker volume rm influxdb-data
   ```

3. **Update docker-compose.yml** to use `influxdb:3-core` image

4. **Start InfluxDB 3 Core:**
   ```bash
   docker-compose up -d influxdb3-core
   ```

5. **Generate admin token** (see Initial Setup above)

6. **Update Grafana datasources** to use SQL instead of Flux

7. **Migrate dashboards** from Flux to SQL queries

**Note:** There is no automatic migration path. Data must be re-ingested.

## Additional Resources

- **Official Documentation**: https://docs.influxdata.com/influxdb3/core/
- **Setup Guide**: [../../INFLUXDB3_SETUP.md](../../INFLUXDB3_SETUP.md)
- **Configuration Guide**: [../../CONFIGURATION_GUIDE.md](../../CONFIGURATION_GUIDE.md)
- **Main README**: [../../README.md](../../README.md)

## Notes

- InfluxDB 3 Core uses **SQL** query language (not Flux)
- Data persists in `influxdb-data` volume
- Health check runs every 30 seconds (process-based, not HTTP)
- No web UI - use Grafana for visualization
- Token stored in InfluxDB catalog (persistent across restarts)
