# PCP Metrics to InfluxDB & Grafana

Automated system for processing PCP (Performance Co-Pilot) archive files and visualizing metrics in Grafana via InfluxDB.

## Table of Contents
- [Overview](#overview)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Directory Structure](#directory-structure)
- [How It Works](#how-it-works)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting)

## Overview

This project provides a complete monitoring solution for PCP (Performance Co-Pilot) metrics:
- Automatically processes PCP archive files
- Stores metrics in InfluxDB time-series database
- Visualizes data through Grafana dashboards
- Provides comprehensive logging and error handling

## Architecture

### Component Overview

```
┌─────────────┐
│  PCP Archive│
│   (.tar.xz) │
└──────┬──────┘
       │
       ▼
┌─────────────────┐      ┌──────────────┐      ┌──────────────┐
│   PCP Parser    │─────▶│   InfluxDB   │─────▶│   Grafana    │
│   Container     │      │   (Port 8086)│      │ (Port 3000)  │
└─────────────────┘      └──────────────┘      └──────────────┘
       │
       ▼
┌─────────────────┐
│  Logs & Archive │
└─────────────────┘
```

### Containers

1. **InfluxDB** (`influxdb:2.7-alpine`)
   - Time-series database for storing metrics
   - Port: 8086
   - Organization: pcp-org
   - Bucket: pcp-metrics
   - Health-checked before dependent services start

2. **Grafana** (`grafana/grafana:latest`)
   - Visualization and dashboarding
   - Port: 3000 (http://localhost:3000)
   - Auto-provisions InfluxDB datasource
   - Pre-configured dashboards for system metrics
   - Credentials: admin/admin

3. **PCP Parser** (Custom Ubuntu 22.04)
   - Processes PCP archives from input directory
   - Extracts metrics using PCP tools
   - Exports to InfluxDB using Flux protocol
   - Automatic archive management (processed/failed)

## Prerequisites

- **Docker Desktop** installed and running
- **Docker Compose** (included with Docker Desktop)
- **Git** (optional, for version control)
- **VS Code** (optional, recommended for easier management)
- PCP archive files in `.tar.xz` format

## Directory Structure

```
PCP/
├── src/                              # All source code, data, and orchestration
│   ├── docker-compose.yml            # ⭐ Main orchestration file
│   │
│   ├── pcp_parser/                   # PCP Parser container code
│   │   ├── Dockerfile                # Parser container build file
│   │   ├── pcp_parser.py             # Main Python parser script
│   │   └── process-pcp-archive.sh    # Bash processing script
│   │
│   ├── influxdb/                     # InfluxDB configuration (optional)
│   │   ├── config/                   # Custom config files
│   │   ├── init-scripts/             # Initialization scripts
│   │   └── README.md                 # InfluxDB setup guide
│   │
│   ├── grafana/                      # Grafana provisioning
│   │   └── provisioning/
│   │       ├── datasources/          # InfluxDB datasource config
│   │       │   └── influxdb.yml
│   │       └── dashboards/           # Dashboard provisioning
│   │           ├── dashboard.yml
│   │           ├── json/             # Dashboard JSON files
│   │           └── json_disabled/    # Temporarily disabled dashboards
│   │
│   ├── input/                        # Input directory
│   │   └── raw/                      # ⭐ Place .tar.xz files here
│   │
│   ├── archive/                      # Archive management
│   │   ├── processed/                # Successfully processed archives
│   │   └── failed/                   # Failed archives for inspection
│   │
│   └── logs/                         # Container logs (by container)
│       ├── grafana/
│       ├── influxdb/
│       └── pcp_parser/
│
├── scripts/                          # Management utility scripts
│   ├── collect_logs.sh               # Collect all container logs
│   ├── collect_logs.bat              # Windows version
│   ├── monitor_logs.bat              # Continuous log monitoring
│   └── start_with_logging.sh         # Start with auto-logging
│
├── sampleData/                       # Sample PCP archives for testing
├── README.md                         # This file
└── DIRECTORY_STRUCTURE.md            # Detailed structure docs
```

## How It Works

### Data Flow

1. **Input**: Place PCP archive files (`.tar.xz`) in `src/input/raw/`

2. **Detection**: PCP Parser polls the input directory every 10 seconds

3. **Processing**:
   - Extracts `.tar.xz` archive
   - Validates PCP archive structure
   - Converts PCP metrics to InfluxDB line protocol
   - Writes data to InfluxDB using Flux

4. **Archival**:
   - **Success**: **DELETES** archive file after successful processing
   - **Failure**: Moves archive to `src/archive/failed/`
   - **Note**: The `processed/` folder exists but is **NOT currently used** by the code
   - Logs all operations with timestamps

5. **Visualization**: Grafana queries InfluxDB and displays dashboards

### Processing Details

**PCP Parser Container**:
- Built on Ubuntu 22.04 with PCP tools
- Python 3 with influxdb-client library
- Runs `pcp_parser.py` as main process
- Watches `/src/input/raw/` for new archives
- Processes archives sequentially to avoid conflicts

**Supported Metrics** (PSOC System):
- CPU frequency (8 cores: cpu0-cpu7)
- Temperature sensors (4 sensors: psoc, sensor1-3)
- Voltage rails (14 rails: 1v0, 1v2, 1v5, 1v8, 2v5, 3v3, 5v, 12v, vbus, vholdup, etc.)
- Current draw (4 buses: 3v3bus, 5vbus, 12vbus, poe)
- Fan metrics (RPM, duty cycle, status)
- Heater status and control
- System status flags (power, fan, heater states)
- 100+ unique PSOC metrics tracked

**Data Filtering**:
- Zero values are filtered out and not exported to InfluxDB
- Empty, None, N/A, and null values are skipped
- Only non-zero metrics are tracked in metrics_labels.csv
- Reduces storage by ~76% compared to unfiltered data

**Data Retention**:
- InfluxDB default retention: Infinite
- Configure retention policies via InfluxDB API if needed

## Quick Start

### Method 1: Using Docker Compose (Command Line)

```bash
# Navigate to src directory
cd src

# Start all containers
docker-compose up -d

# Check container status
docker-compose ps

# View logs
docker-compose logs -f

# Stop containers
docker-compose down
```

### Method 2: Using VS Code Docker Extension

1. **Install Docker Extension**:
   - Open VS Code
   - Go to Extensions (Ctrl+Shift+X)
   - Search for "Docker" by Microsoft
   - Install

2. **Start Containers**:
   - Open project folder in VS Code
   - Navigate to `src/docker-compose.yml` in Explorer
   - Right-click `docker-compose.yml`
   - Select "Compose Up"

3. **Monitor**:
   - Click Docker icon in sidebar
   - View running containers
   - Right-click for logs, restart, etc.

### Accessing Services

- **Grafana**: http://localhost:3000
  - Username: `admin`
  - Password: `admin`

- **InfluxDB**: http://localhost:8086
  - Username: `admin`
  - Password: `adminadmin`
  - Org: `pcp-org`
  - Token: `pcp-admin-token-12345`

## Usage

### Adding PCP Archives

1. Place your `.tar.xz` PCP archive files in:
   ```
   src/input/raw/
   ```

2. The parser will automatically:
   - Detect new files (polling every 10 seconds)
   - Extract and process them
   - Import metrics to InfluxDB
   - Filter out zero/null values
   - Track unique metrics in metrics_labels.csv
   - **Delete** successfully processed archives
   - Move failed archives to `archive/failed/`

### Viewing Dashboards

1. Open Grafana at http://localhost:3000
2. Login (admin/admin)
3. Navigate to **Dashboards** → **PCP System Metrics**
4. View **8 comprehensive panels**:
   - **CPU Frequency** - 8 cores (cpu0-cpu7) in MHz
   - **Temperature Sensors** - 4 sensors (psoc, sensor1-3) in °C
   - **Voltage Rails** - 14 voltage rails (1v0, 1v2, 1v5, 1v8, 2v5, 3v3, 5v, 12v, etc.)
   - **Current Draw** - 4 power buses (3v3, 5v, 12v, POE) in Amps
   - **Fan Speed (RPM)** - Real-time fan RPM monitoring
   - **Fan Duty Cycle** - Fan speed control percentage
   - **Heater Metrics** - All heater-related metrics
   - **System Status Flags** - All system status indicators

**Dashboard Features**:
- Auto-refresh every 30 seconds
- 7-day default time range
- Mean, max, and last value calculations
- Proper units and formatting (Hz, °C, V, A, RPM, %)

### Live Logging

All three containers provide **live, real-time logs** written directly to mounted volumes:

- `src/logs/grafana/grafana.log` - Grafana server logs (updates in real-time)
- `src/logs/influxdb/influxdb.log` - InfluxDB server logs (updates in real-time)
- `src/logs/pcp_parser/pcp_parser.log` - Parser processing logs (updates in real-time)

**Viewing Live Logs**:

**Linux/Mac**:
```bash
# View Grafana logs
tail -f src/logs/grafana/grafana.log

# View InfluxDB logs
tail -f src/logs/influxdb/influxdb.log

# View parser logs
tail -f src/logs/pcp_parser/pcp_parser.log
```

**Windows PowerShell**:
```powershell
# View Grafana logs
Get-Content src/logs/grafana/grafana.log -Wait -Tail 50

# View InfluxDB logs
Get-Content src/logs/influxdb/influxdb.log -Wait -Tail 50

# View parser logs
Get-Content src/logs/pcp_parser/pcp_parser.log -Wait -Tail 50
```

**Log Configuration**:
- **InfluxDB**: Uses `tee` command to write to both stdout and file
- **Grafana**: Uses native file logging via `GF_LOG_MODE=file`
- **PCP Parser**: Direct Python logging to file

**Legacy Scripts** (Optional):
```bash
# Manual log collection (Linux/Mac)
bash scripts/collect_logs.sh

# Manual log collection (Windows)
scripts\collect_logs.bat

# Continuous monitoring (Windows)
scripts\monitor_logs.bat
```

### Metrics Tracking

The system automatically tracks all unique non-zero metrics in:
```
src/logs/pcp_parser/metrics_labels.csv
```

This CSV file contains:
- All unique metric names that have been ingested
- Only metrics with actual non-zero values
- Updated in real-time as new archives are processed
- Useful for discovering available metrics and dashboard creation

**Example**:
```bash
# View tracked metrics
cat src/logs/pcp_parser/metrics_labels.csv

# Count unique metrics
wc -l src/logs/pcp_parser/metrics_labels.csv
```

### Checking Processing Status

```bash
# View parser logs (live)
tail -f src/logs/pcp_parser/pcp_parser.log

# View container logs
docker logs pcp_parser

# Check failed archives
ls -la src/archive/failed/

# Note: Successful archives are deleted, not moved to processed/
```

## Monitoring

### Container Health

```bash
# Check all containers
docker ps

# Check specific container
docker logs grafana
docker logs influxdb
docker logs pcp_parser

# Check container resource usage
docker stats
```

### InfluxDB Queries

Access InfluxDB UI at http://localhost:8086 and run Flux queries:

```flux
from(bucket: "pcp-metrics")
  |> range(start: -1h)
  |> filter(fn: (r) => r["_measurement"] == "pcp_metrics")
  |> filter(fn: (r) => r["metric"] =~ /cpu/)
```

### Grafana Data Source

The InfluxDB datasource is auto-provisioned with:
- URL: `http://influxdb:8086`
- Organization: `pcp-org`
- Default Bucket: `pcp-metrics`
- Token: `pcp-admin-token-12345`

## Troubleshooting

### Grafana Won't Start or Keeps Restarting

**Problem**: Corrupted Grafana volume or datasource issues

**Solution**:
```bash
docker-compose down
docker volume rm pcp_grafana-data
docker-compose up -d
```

### No Data in Grafana

**Check**:
1. Verify InfluxDB is running and healthy:
   ```bash
   docker ps | grep influxdb
   ```

2. Verify datasource connection in Grafana:
   - Settings → Data Sources → InfluxDB
   - Click "Test" button

3. Check if data exists in InfluxDB:
   - Go to http://localhost:8086
   - Navigate to Data Explorer
   - Query the `pcp-metrics` bucket

### Archives Not Processing

**Check**:
1. Verify pcp_parser is running:
   ```bash
   docker logs pcp_parser
   ```

2. Check file permissions:
   ```bash
   ls -la src/input/raw/
   ```

3. Verify archive format (must be `.tar.xz`)

4. Check failed archives directory:
   ```bash
   ls -la src/archive/failed/
   ```

### Container Logs Not Appearing

**Solution**: Run the log collection script:
```bash
bash scripts/collect_logs.sh
```

This manually collects logs from Docker's internal storage to `src/logs/`

### Permission Errors

**Windows**:
- Run Docker Desktop as Administrator
- Ensure file sharing is enabled for the project directory

**Linux**:
```bash
sudo chown -R $USER:$USER src/
```

## Configuration

### Changing InfluxDB Credentials

Edit `docker-compose.yml`:
```yaml
environment:
  - DOCKER_INFLUXDB_INIT_ADMIN_TOKEN=your-new-token
```

Also update:
- `src/grafana/provisioning/datasources/influxdb.yml`
- pcp_parser environment variable in docker-compose.yml

### Grafana Configuration

**Custom Settings** (via grafana.ini):
- Password change disabled on first login
- Fixed credentials: admin/admin
- Native file logging enabled
- Auto-provisioning enabled for datasources and dashboards

**File Logging**:
- Mode: File (not console)
- Level: Info
- Path: /var/log/grafana (mounted to src/logs/grafana/)

**Changing Grafana Password**:

Edit `docker-compose.yml`:
```yaml
environment:
  - GF_SECURITY_ADMIN_PASSWORD=your-new-password
```

Or edit `src/grafana/config/grafana.ini`:
```ini
[security]
admin_password = your-new-password
```

### Adding Custom Dashboards

1. Create dashboard in Grafana UI
2. Export as JSON
3. Place in `src/grafana/provisioning/dashboards/json/`
4. Restart Grafana or wait 30 seconds for auto-reload

## Maintenance

### Clean Up Old Logs

```bash
# Remove logs older than 7 days
find src/logs -name "*_202*" -mtime +7 -delete
```

### Remove Processed Archives

```bash
# Clean up processed archives
rm src/archive/processed/*.tar.xz
```

### Reset Everything

```bash
# Stop and remove everything
docker-compose down -v

# Remove all data volumes
docker volume rm pcp_grafana-data pcp_influxdb-data

# Start fresh
docker-compose up -d
```

## Documentation

- **DIRECTORY_STRUCTURE.md** - Complete directory structure documentation
- **FIXES_APPLIED.md** - Documented bug fixes and solutions
- **docker-compose.yml** - Service configuration and orchestration

## Support

For issues or questions:
1. Check the [Troubleshooting](#troubleshooting) section
2. Review container logs: `bash scripts/collect_logs.sh`
3. Verify all prerequisites are met
4. Check Docker Desktop is running

## License

This project is for internal use and monitoring of PCP metrics.
