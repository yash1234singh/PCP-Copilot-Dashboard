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
- [Dynamic Dashboard Generation](#dynamic-dashboard-generation)
- [Performance Tuning](#performance-tuning)
- [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting)

## Overview

This project provides a complete monitoring solution for PCP (Performance Co-Pilot) metrics:
- Automatically processes PCP archive files
- Stores metrics in InfluxDB time-series database
- Visualizes data through Grafana dashboards
- Provides comprehensive logging and error handling

## Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                     PCP METRICS PIPELINE                          │
└──────────────────────────────────────────────────────────────────┘

┌─────────────┐
│ PCP Archive │  .tar.xz files from monitoring system
│  (.tar.xz)  │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PCP PARSER CONTAINER                          │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  1. ARCHIVE EXTRACTION                                  │    │
│  │     - Watches /src/input/raw for .tar.xz files         │    │
│  │     - Extracts to /tmp/pcp_archives                    │    │
│  │     - Finds .meta file to locate PCP archive           │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  2. METRIC DISCOVERY & VALIDATION                       │    │
│  │     - pminfo: Discovers all metrics in archive         │    │
│  │     - Batch validation (1000 metrics at a time)        │    │
│  │     - Filters out invalid/derived metrics              │    │
│  │     - Category filtering (process/disk/mem/etc)        │    │
│  │     - Caches validated metrics for reuse               │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  3. DATA EXTRACTION                                     │    │
│  │     - pmrep: Exports validated metrics to CSV          │    │
│  │     - Parses CSV with timestamp + metric columns       │    │
│  │     - Applies value filters (skip empty/null)          │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  4. INFLUXDB EXPORT                                     │    │
│  │     - Async batch writes (50k points/batch)            │    │
│  │     - Adds static tags (product_type, serialNumber)    │    │
│  │     - Parallel processing with retry logic             │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  5. ARCHIVE MANAGEMENT                                  │    │
│  │     - Success: Removes processed archive               │    │
│  │     - Failure: Moves to /src/archive/failed            │    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────┐      ┌──────────────────┐
│    INFLUXDB      │      │   METRICS CSV    │
│  Time-series DB  │      │  Tracking File   │
│  (Port 8086)     │      │ metrics_labels   │
└────────┬─────────┘      └──────────────────┘
         │
         ▼
┌──────────────────┐      ┌──────────────────┐
│     GRAFANA      │      │  AUTO DASHBOARD  │
│  Visualization   │◄─────┤   GENERATOR      │
│  (Port 3000)     │      │  Python script   │
└──────────────────┘      └──────────────────┘
```

### Data Model

**InfluxDB Structure:**
```
measurement: pcp_metrics
├── tags
│   ├── metric (metric name)
│   ├── product_type (L5E)
│   └── serialNumber (341100896)
├── fields
│   └── value (float)
└── timestamp (nanoseconds)
```

### Processing Flow

**Archive Processing Sequence:**
```
1. Archive arrives → /src/input/raw/20250915.tar.xz

2. Extraction → /tmp/pcp_archives/20250915.tar/20250915.{meta,index,0}

3. Discovery → pminfo -a <archive> → ~2000 raw metrics

4. Validation → pmrep batch test → ~1870 valid metrics

5. Filtering → Category filters → 300-1870 metrics (configurable)

6. Caching → /src/logs/pcp_parser/validated_metrics.txt

7. Export → pmrep CSV → InfluxDB points (async batches)

8. Cleanup → Archive removed or moved to failed/
```

**Metric Validation Process:**
```
Input: ~2000 metrics from pminfo

Step 1: Batch Test (1000 metrics at a time)
├── pmrep -a <archive> -s 1 -o csv <1000 metrics>
├── Success: All 1000 metrics valid
└── Failure: Test each individually

Step 2: Individual Test (for failed batches)
├── pmrep -a <archive> -s 1 -o csv <single metric>
├── Success: Add to valid list
└── Failure: Filter out (PM_ERR_BADDERIVE, etc.)

Step 3: Category Filtering
├── ENABLE_PROCESS_METRICS=false → Remove proc.* (~10k columns)
├── ENABLE_DISK_METRICS=true → Keep disk.*
└── ... (7 category filters total)

Output: 300-1870 validated metrics
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
   - Extract and validate metrics
   - Apply category filters (process/disk/memory/etc)
   - Export to InfluxDB with async batch writes
   - Track metrics in metrics_labels.csv
   - **Delete** successfully processed archives
   - Move failed archives to `archive/failed/`

### Key Commands

**Monitor Processing:**
```bash
# Watch parser logs in real-time
docker logs pcp-parser -f

# Check validated metrics cache
docker exec pcp-parser cat /src/logs/pcp_parser/validated_metrics.txt | wc -l

# View all discovered metrics
docker exec pcp-parser head -20 /src/logs/pcp_parser/metrics_labels.csv
```

**Regenerate Dashboard:**
```bash
cd src/grafana
python generate_dashboard.py
# Dashboard auto-reloads in Grafana within 30 seconds
```

**Force Cache Rebuild:**
```yaml
# In docker-compose.yml
- FORCE_REVALIDATE=true  # Set to true
# Then restart: docker-compose restart pcp-parser
# Then set back to false after first run
```

**Manage Data:**
```bash
# Check InfluxDB data
docker exec influxdb influx query 'from(bucket:"pcp-metrics") |> range(start:-1h) |> count()'

# Clear all data (WARNING: Deletes everything!)
docker-compose down -v
docker-compose up -d
```

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

## Dynamic Dashboard Generation

The system includes an **auto-generated dashboard** that creates panels for all discovered metrics from your PCP archives.

### Auto-Generated Dashboard

**Location**: http://localhost:3000/d/pcp-auto-metrics/pcp-auto-generated-metrics-dashboard

**Features**:
- ✅ **Automatically includes ALL metrics** from `metrics_labels.csv`
- ✅ **Hierarchical organization** by metric category (14 top-level groups)
- ✅ **Collapsible rows** - clean interface, expand only what you need
- ✅ **9,040+ metrics** organized into 1,043 panels
- ✅ **Auto-updates** when new metrics are discovered

**Structure**:
```
[DISK] - 4 subcategories, 310 metrics
  [disk.all] (16 metrics)
  [disk.dev] (46 metrics)
  [disk.dm] (184 metrics)
  [disk.partitions] (64 metrics)

[KERNEL] - 3 subcategories, 147 metrics
  [kernel.all] (28 metrics)
  [kernel.cpu] (7 metrics)
  [kernel.percpu] (112 metrics)

[MEM] - 8 subcategories, 375 metrics
[NETWORK] - 10 subcategories, 1154 metrics
[PROC] - 4 subcategories, 6573 metrics
[PSOC] - 4 subcategories, 312 metrics
... and 8 more groups
```

### Regenerating the Dashboard

If you want to update the dashboard with newly discovered metrics:

```bash
cd src/grafana
python generate_dashboard.py
```

**Output**: `provisioning/dashboards/json/pcp-auto-dashboard.json`

**When to regenerate**:
- After processing new PCP archives with different metrics
- When `metrics_labels.csv` has been updated
- To reorganize or customize the dashboard structure

**Dashboard will auto-reload** in Grafana within 30 seconds

### Dashboard Generator Script

The generator script (`src/grafana/generate_dashboard.py`) automatically:

1. **Reads** `src/logs/pcp_parser/metrics_labels.csv`
2. **Organizes** metrics hierarchically by prefix (disk.*, kernel.*, mem.*, etc.)
3. **Creates** collapsible rows for each category
4. **Generates** panels with up to 10 metrics each
5. **Writes** dashboard JSON to provisioning directory

**Customization**:
- Edit `generate_dashboard.py` to change:
  - Metrics per panel (default: 10)
  - Panel layout (default: 2 panels per row)
  - Time range (default: last 6 hours)
  - Refresh interval (default: 30 seconds)

See `src/grafana/DASHBOARD_README.md` for detailed documentation.

## Performance Tuning

The PCP parser includes configurable performance parameters for optimal processing speed.

### Current Performance

**Processing Speed** (with optimizations):
- **First archive**: ~2.5 minutes (validation + export)
- **Subsequent archives**: ~2 minutes (cached validation + export)

**Speedup**: 2-5x faster than original implementation

### Configuration Parameters

All parameters are configurable via environment variables in `docker-compose.yml`:

#### 1. FORCE_REVALIDATE (Validation Cache) ⚡
**Default**: `false`

Controls whether to use cached validated metrics or revalidate every time.

```yaml
- FORCE_REVALIDATE=false  # Use cache (fast)
- FORCE_REVALIDATE=true   # Force revalidation (slower but thorough)
```

**How it works**:
- **First archive**: Validates 1976 metrics, saves to cache (~50 seconds)
- **Subsequent archives**: Loads from cache (~1 second) ⚡ **50 seconds faster**

**Cache file**: `src/logs/pcp_parser/validated_metrics.txt` (1882 valid metrics)

**When to force revalidation**:
- After upgrading PCP version
- When metrics change in your system
- Troubleshooting validation issues

#### 2. VALIDATION_BATCH_SIZE
**Default**: `100`

Number of metrics to validate together in each batch.

```yaml
- VALIDATION_BATCH_SIZE=100   # Standard (recommended)
- VALIDATION_BATCH_SIZE=200   # Faster validation
- VALIDATION_BATCH_SIZE=50    # More granular error detection
```

#### 3. INFLUX_BATCH_SIZE
**Default**: `50000`

Number of data points to accumulate before writing to InfluxDB.

```yaml
- INFLUX_BATCH_SIZE=50000    # Standard (recommended)
- INFLUX_BATCH_SIZE=100000   # Faster, more memory
- INFLUX_BATCH_SIZE=25000    # Slower, less memory
```

#### 4. PROGRESS_LOG_INTERVAL
**Default**: `50`

How often to log progress (every N batches).

```yaml
- PROGRESS_LOG_INTERVAL=50   # Standard (recommended)
- PROGRESS_LOG_INTERVAL=100  # Less logging
- PROGRESS_LOG_INTERVAL=10   # More detailed logging
```

### Example Configurations

**High-Performance** (fast systems with 16GB+ RAM):
```yaml
- FORCE_REVALIDATE=false
- VALIDATION_BATCH_SIZE=200
- INFLUX_BATCH_SIZE=100000
- PROGRESS_LOG_INTERVAL=100
```

**Standard** (balanced, recommended):
```yaml
- FORCE_REVALIDATE=false
- VALIDATION_BATCH_SIZE=100
- INFLUX_BATCH_SIZE=50000
- PROGRESS_LOG_INTERVAL=50
```

**Low-Resource** (4GB RAM, slower CPU):
```yaml
- FORCE_REVALIDATE=false
- VALIDATION_BATCH_SIZE=50
- INFLUX_BATCH_SIZE=10000
- PROGRESS_LOG_INTERVAL=25
```

### Performance Impact

| Archive Size | Metrics | Data Points | Time (Optimized) |
|-------------|---------|-------------|------------------|
| 24 hours    | 1,875   | 4M points   | ~8-12 minutes    |
| 7 days      | 1,875   | 28M points  | ~1 hour          |
| 30 days     | 1,875   | 120M points | ~5 hours         |

**Note**: Times assume `ENABLE_PROCESS_METRICS=false` (recommended). With process metrics enabled, processing can take 5-10x longer due to 10,000+ columns.

### Metric Category Filters

Control which metric categories to include/exclude for faster processing:

```yaml
# Metric category filters (set to false to exclude that category)
- ENABLE_PROCESS_METRICS=false    # proc.* (⚠️ creates 10k+ columns if enabled!)
- ENABLE_DISK_METRICS=true        # disk.* metrics
- ENABLE_FILE_METRICS=true        # vfs.* and filesys.* metrics
- ENABLE_MEMORY_METRICS=true      # mem.* metrics
- ENABLE_NETWORK_METRICS=true     # network.* metrics
- ENABLE_KERNEL_METRICS=true      # kernel.* metrics
- ENABLE_SWAP_METRICS=true        # swap.* metrics
```

**When to disable categories**:
- **Process metrics**: Always disable unless specifically needed (reduces 10k+ columns to ~300)
- **Swap metrics**: Disable if system doesn't use swap
- **Network metrics**: Disable if only monitoring local metrics

**Cache rebuild required**: After changing filters, set `FORCE_REVALIDATE=true`, restart container, then set back to `false`.

### Value Filtering

Skip specific value types to reduce storage:

```yaml
# Value filtering (comma-separated: skip_zero, skip_empty, skip_none)
- PCP_METRICS_FILTER=skip_empty,skip_none
```

**Options**:
- `skip_zero`: Skip zero values (⚠️ WARNING: may filter useful metrics like idle time!)
- `skip_empty`: Skip empty string values
- `skip_none`: Skip null/none values

**Recommended**: `skip_empty,skip_none` (without skip_zero)


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

### Main Documentation
- **README.md** (this file) - Complete setup and usage guide
- **DIRECTORY_STRUCTURE.md** - Complete directory structure documentation
- **FIXES_APPLIED.md** - Documented bug fixes and solutions
- **docker-compose.yml** - Service configuration and orchestration

### Performance & Optimization
- **src/PERFORMANCE_TUNING.md** - Detailed performance tuning guide
  - Validation caching
  - Batch size optimization
  - Configuration examples
  - Troubleshooting performance issues

### Dashboard Documentation
- **src/grafana/DASHBOARD_README.md** - Auto-generated dashboard documentation
  - Dashboard structure and organization
  - Metrics hierarchy (14 groups, 83 subcategories, 9040+ metrics)
  - How to regenerate dashboards
  - Customization guide
- **src/grafana/generate_dashboard.py** - Dashboard generator script

### Key Files
- **src/logs/pcp_parser/metrics_labels.csv** - All discovered non-zero metrics
- **src/logs/pcp_parser/validated_metrics.txt** - Cached validated metrics (auto-generated)
- **src/logs/pcp_parser/pcp_parser.log** - Real-time parser processing logs

## Troubleshooting

### Issue: 0 Data Points Written

**Symptoms:**
```
Total data points written: 0
Processed 0 lines from pmrep
```

**Causes & Solutions:**

1. **SKIP_VALIDATION=true** (most common cause)
   ```yaml
   # In docker-compose.yml - NEVER enable this!
   - SKIP_VALIDATION=false  # ✅ Correct
   - SKIP_VALIDATION=true   # ❌ Causes 0 data points
   ```

2. **Overly aggressive value filtering**
   ```yaml
   # Remove skip_zero - it filters legitimate zero values
   - PCP_METRICS_FILTER=skip_empty,skip_none  # ✅ Correct
   - PCP_METRICS_FILTER=skip_zero,skip_empty  # ❌ May filter all data
   ```

3. **Old cache with wrong metrics**
   ```bash
   # Delete cache and rebuild
   rm src/logs/pcp_parser/validated_metrics.txt
   docker-compose restart pcp_parser
   ```

### Issue: Processing Takes 60+ Minutes Per Archive

**Symptoms:**
```
Found 10896 columns (first column is timestamp)
⏱️  TOTAL PROCESSING TIME: 65 minutes 14.31 seconds
```

**Cause**: Process metrics enabled (creates 10,000+ columns)

**Solution**:
```yaml
# In docker-compose.yml
- ENABLE_PROCESS_METRICS=false  # ✅ Reduces to ~3000 columns
- FORCE_REVALIDATE=true         # Rebuild cache

# Restart
docker-compose restart pcp_parser

# After first run, disable force revalidate
- FORCE_REVALIDATE=false
```

**Expected improvement**: 65 minutes → 8-12 minutes (5-8x faster!)

### Issue: PM_ERR_BADDERIVE or PM_ERR_INDOM_LOG Errors

**Symptoms:**
```
pmrep stderr: Invalid metric disk.dev.d_await (PM_ERR_BADDERIVE)
pmrep stderr: Invalid metric nfs.client.reqs (PM_ERR_INDOM_LOG)
```

**Explanation**: Normal - derived metrics or metrics with missing instance domains

**Impact**: None - validation filters these out automatically

**Action**: No action needed - these warnings are expected and handled

### Issue: Cache Not Working (Always Revalidating)

**Symptoms:**
```
No validation cache found, will validate metrics
Found 1982 total metrics, validating each one...
```

**Solutions**:

1. **Check FORCE_REVALIDATE setting**
   ```yaml
   - FORCE_REVALIDATE=false  # Should be false for cache usage
   ```

2. **Verify cache file exists**
   ```bash
   ls -la src/logs/pcp_parser/validated_metrics.txt
   ```

3. **Check file permissions**
   ```bash
   chmod 644 src/logs/pcp_parser/validated_metrics.txt
   ```

### Issue: High Memory Usage

**Cause**: Batch sizes too large for available RAM

**Solution**:
```yaml
# Reduce batch sizes
- VALIDATION_BATCH_SIZE=50      # Down from 1000
- INFLUX_BATCH_SIZE=10000       # Down from 50000
```

### Issue: Grafana Dashboard Not Showing Data

**Checks**:

1. **Verify InfluxDB has data**
   ```bash
   docker exec influxdb influx query 'from(bucket:"pcp-metrics") |> range(start:-1h) |> count()'
   ```

2. **Check datasource connection**
   - Grafana → Configuration → Data Sources → InfluxDB
   - Click "Test" button
   - Should show "Data source is working"

3. **Verify time range**
   - Check dashboard time picker (top right)
   - Ensure it covers the period when archives were processed

4. **Check bucket name**
   - Dashboard queries should use bucket: `pcp-metrics`
   - Org: `pcp-org`

### Issue: Container Won't Start

**Check logs**:
```bash
docker-compose logs pcp_parser
docker-compose logs influxdb
docker-compose logs grafana
```

**Common fixes**:
```bash
# Port conflict - another service using 3000/8086
docker-compose down
# Change ports in docker-compose.yml if needed

# Volume permission issues
docker-compose down -v
docker-compose up -d

# Image pull issues
docker-compose pull
docker-compose up -d
```

### Issue: Archives Not Being Processed

**Checks**:

1. **Verify files in correct directory**
   ```bash
   ls -la src/input/raw/*.tar.xz
   ```

2. **Check parser is running**
   ```bash
   docker ps | grep pcp_parser
   ```

3. **Review parser logs**
   ```bash
   docker logs pcp_parser -f
   ```

4. **File permissions**
   ```bash
   chmod 644 src/input/raw/*.tar.xz
   ```

### Getting Help

**Collect diagnostic information**:
```bash
# Collect all logs
bash scripts/collect_logs.sh

# Check system status
docker-compose ps
docker stats --no-stream

# View recent parser activity
docker logs pcp_parser --tail 100

# Check validated metrics count
wc -l src/logs/pcp_parser/validated_metrics.txt
```

**Log locations**:
- Parser: `src/logs/pcp_parser/pcp_parser.log`
- InfluxDB: `docker logs influxdb`
- Grafana: `docker logs grafana`

## Support

For issues or questions:
1. Check the [Troubleshooting](#troubleshooting) section above
2. Review container logs: `bash scripts/collect_logs.sh`
3. Verify all prerequisites are met
4. Check Docker Desktop is running

## License

This project is for internal use and monitoring of PCP metrics.
