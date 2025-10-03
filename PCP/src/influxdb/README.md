# InfluxDB Configuration

This directory contains InfluxDB configuration and initialization files.

## Structure

```
influxdb/
├── config/         # Custom InfluxDB configuration files (optional)
├── init-scripts/   # Initialization scripts (optional)
└── README.md       # This file
```

## Current Configuration

InfluxDB is currently configured entirely through environment variables in `docker-compose.yml`:

```yaml
environment:
  - DOCKER_INFLUXDB_INIT_MODE=setup
  - DOCKER_INFLUXDB_INIT_USERNAME=admin
  - DOCKER_INFLUXDB_INIT_PASSWORD=adminpassword
  - DOCKER_INFLUXDB_INIT_ORG=pcp-org
  - DOCKER_INFLUXDB_INIT_BUCKET=pcp-metrics
  - DOCKER_INFLUXDB_INIT_ADMIN_TOKEN=pcp-admin-token-12345
  - INFLUXDB_HTTP_AUTH_ENABLED=true
```

## Data Storage

Data is stored in a Docker volume: `influxdb-data`

This volume persists:
- Database files
- Indexes
- WAL (Write-Ahead Log)
- User data

## Future Enhancements

### Custom Configuration

To add custom InfluxDB configuration:

1. Create `config/influxdb.conf`:
   ```toml
   [http]
   bind-address = ":8086"

   [logging]
   level = "info"
   ```

2. Mount in docker-compose.yml:
   ```yaml
   volumes:
     - ./src/influxdb/config/influxdb.conf:/etc/influxdb2/influxdb.conf:ro
   ```

### Initialization Scripts

To run scripts on first start:

1. Create script in `init-scripts/`:
   ```bash
   #!/bin/bash
   # init-scripts/setup.sh
   influx bucket create -n additional-bucket
   ```

2. Mount in docker-compose.yml:
   ```yaml
   volumes:
     - ./src/influxdb/init-scripts:/docker-entrypoint-initdb.d:ro
   ```

## Access

- **UI**: http://localhost:8086
- **API**: http://localhost:8086/api/v2
- **Username**: admin
- **Password**: adminpassword
- **Organization**: pcp-org
- **Default Bucket**: pcp-metrics

## Maintenance

### Backup

```bash
docker exec influxdb influx backup /backup
docker cp influxdb:/backup ./backup
```

### Restore

```bash
docker cp ./backup influxdb:/backup
docker exec influxdb influx restore /backup
```

### Query Data

```bash
docker exec -it influxdb influx query 'from(bucket:"pcp-metrics") |> range(start: -1h)'
```

## Notes

- InfluxDB 2.x uses Flux query language (not InfluxQL)
- Data persists in `influxdb-data` volume
- Health check runs every 10 seconds on `/health` endpoint
