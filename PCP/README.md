# PCP Metrics to InfluxDB & Grafana

Automated system for processing PCP (Performance Co-Pilot) archive files and visualizing metrics in Grafana via InfluxDB.

## Table of Contents
- [Overview](#overview)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Directory Structure](#directory-structure)
- [How It Works](#how-it-works)
- [Quick Start](#quick-start)
- [Web Control Panel](#web-control-panel)
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

**InfluxDB Structure (Field-Based):**
```
measurement: pcp_metrics
├── tags
│   ├── product_type (filterable, configurable via web UI)
│   └── serialNumber (filterable, configurable via web UI)
├── fields
│   ├── kernel_all_cpu_idle (float)
│   ├── kernel_all_cpu_user (float)
│   ├── mem_util_free (float)
│   └── ... (all metrics as separate fields)
└── timestamp (nanoseconds)
```

**Benefits of Field-Based Model:**
- **Low Cardinality** - Only 2 tags instead of 1 tag per metric
- **Better Performance** - Single point per timestamp instead of thousands
- **Easier Queries** - Field regex matching (`r["_field"] =~ /pattern/`)
- **Scalable** - Supports thousands of metrics efficiently

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

3. **PCP Parser - Python** (Custom Ubuntu 22.04)
   - Processes PCP archives from input directory
   - Extracts metrics using PCP tools
   - Exports to InfluxDB using Flux protocol
   - Trigger-based processing (manual start via web UI)
   - Field-based data model for optimal performance
   - Automatic archive management (processed/failed)
   - Watches for `/src/.process_trigger_python`

4. **PCP Parser - Go** (Custom Ubuntu 22.04)
   - Go-based implementation for improved performance
   - 6-10x faster startup time compared to Python
   - 4-5x less memory usage
   - Same functionality as Python parser
   - Increased buffer size for handling large CSV files (10MB per line)
   - Watches for `/src/.process_trigger_go`

5. **Web Control Panel** (`web_pcp_ctrl`)
   - Flask-based web interface
   - Port: 5000 (http://localhost:5000)
   - File upload, management, and processing control
   - **Parser selection** - Choose between Python or Go parser
   - Live log and CSV viewing
   - Configuration management

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
│   ├── .env                          # Environment variables (PRODUCT_TYPE, SERIAL_NUMBER)
│   │
│   ├── pcp_parser/                   # PCP Parser container code
│   │   ├── Dockerfile                # Parser container build file
│   │   └── pcp_parser.py             # Main Python parser script (trigger-based)
│   │
│   ├── web_pcp_ctrl/                 # Web Control Panel container
│   │   ├── Dockerfile                # Web UI container build file
│   │   ├── app.py                    # Flask backend API
│   │   └── templates/
│   │       └── index.html            # Web UI frontend
│   │
│   ├── influxdb/                     # InfluxDB configuration (optional)
│   │   ├── config/                   # Custom config files
│   │   ├── init-scripts/             # Initialization scripts
│   │   └── README.md                 # InfluxDB setup guide
│   │
│   ├── grafana/                      # Grafana provisioning
│   │   ├── generate_dashboard.py     # ⭐ Dashboard generator script
│   │   ├── DASHBOARD_README.md       # Dashboard documentation
│   │   └── provisioning/
│   │       ├── datasources/          # InfluxDB datasource config
│   │       │   └── influxdb.yml
│   │       └── dashboards/           # Dashboard provisioning
│   │           ├── dashboard.yml
│   │           └── json/             # Dashboard JSON files
│   │               ├── pcp-metrics.json         # Manual dashboard
│   │               └── pcp-auto-dashboard.json  # Auto-generated dashboard
│   │
│   ├── input/                        # Input directory
│   │   └── raw/                      # ⭐ Place .tar.xz files here (or upload via web UI)
│   │
│   ├── archive/                      # Archive management
│   │   ├── processed/                # Successfully processed archives
│   │   └── failed/                   # Failed archives for inspection
│   │
│   └── logs/                         # Container logs (by container)
│       ├── grafana/
│       ├── influxdb/
│       └── pcp_parser/
│           ├── pcp_parser.log        # Parser logs
│           ├── metrics_labels.csv    # Discovered metrics
│           ├── validated_metrics.txt # Cached validation
│           └── pmrep_output_*.csv    # CSV output per archive
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

2. **Trigger**: Click "Process All Files" in web interface (creates `.process_trigger` file)

3. **Detection**: PCP Parser detects trigger file every 2 seconds

4. **Processing**:
   - Extracts `.tar.xz` archive
   - Validates PCP archive structure using cached metrics
   - Converts PCP metrics to field-based InfluxDB format
   - Saves CSV output for debugging
   - Writes data to InfluxDB using Flux protocol

4. **Archival**:
   - **Success**: Moves archive to `src/archive/processed/`
   - **Failure**: Moves archive to `src/archive/failed/`
   - **CSV Output**: Saves pmrep output to `src/logs/pcp_parser/pmrep_output_*.csv`
   - Logs all operations with timestamps

5. **Visualization**: Grafana queries InfluxDB and displays dashboards

### Processing Details

**PCP Parser Container**:
- Built on Ubuntu 22.04 with PCP tools
- Python 3 with influxdb-client library
- Runs `pcp_parser.py` as main process
- **Trigger-based processing** - waits for `.process_trigger` file
- Processes archives sequentially to avoid conflicts
- **Field-based data model** - all metrics as fields in single point
- **No timeout logs** - stderr suppressed from pmrep command

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

- **Web Control Panel**: http://localhost:5000
  - Upload and manage PCP archives
  - Trigger processing manually
  - View logs and CSV files
  - **Configure data tagging** - set product type and serial number (required before processing)

- **Grafana**: http://localhost:3000
  - Username: `admin`
  - Password: `admin`

- **InfluxDB**: http://localhost:8086
  - Username: `admin`
  - Password: `adminadmin`
  - Org: `pcp-org`
  - Token: `pcp-admin-token-12345`

## Web Control Panel

The web interface at http://localhost:5000 provides a comprehensive control panel for managing PCP archive processing.

### Features

#### File Management
- **Upload** PCP archive files (.tar.xz) via drag-and-drop or file picker
- **View** files in Input, Processed, and Failed directories
- **Delete** individual files or clear entire directories
- **Statistics** dashboard showing file counts across all directories

#### Processing Control
- **Parser Selection** - Choose between Python or Go parser before processing
  - **Python Parser**: Mature, well-tested implementation
  - **Go Parser**: Faster startup (6-10x), lower memory (4-5x less)
- **Manual Trigger** - Click "Process All Files" button to start processing
- **Status Monitoring** - Real-time processing status with live updates
- **Automatic Archive Management** - Files moved to `archive/processed` or `archive/failed`
- **No Automatic Loop** - Processing only starts when button is clicked
- **Button Disabling** - Process All button disabled during processing to prevent concurrent runs

#### Log Management
- **View Logs** - Click "Watch" to view log files in browser with terminal-style display
- **Live Updates** - Toggle live log streaming (refreshes every 2 seconds)
- **Download** - Download log files for offline viewing
- **Clear Logs** - Bulk delete log files

#### CSV Management
- **View CSV** - View CSV files directly in browser
- **Download CSV** - Download CSV files containing raw pmrep output
- **Clear CSV** - Bulk delete CSV files
- CSV files contain complete pmrep output for each processed archive

#### Configuration Management
- **Product Type** - Set product type for data tagging (default: SERVER1, required field)
- **Serial Number** - Set serial number for data tagging (default: 1234, required field)
- **⚠️ Important**: Configuration must be set **before** processing archives
- All processed data is tagged with these values
- Changes written to `.env` file and automatically applied
- Web UI automatically restarts pcp_parser container when config is updated (~10 seconds)

### Data Flow with Web Control Panel

```
1. Upload .tar.xz → Web UI → /src/input/raw/
2. Select parser (Python or Go) → Radio button selection
3. Click "Process All Files" → Creates parser-specific trigger file
   - Python: /src/.process_trigger_python
   - Go: /src/.process_trigger_go
4. Selected parser detects trigger → Starts processing
5. Extract metrics → pmrep command → CSV output
6. Write to InfluxDB → Field-based data model
7. Save CSV → /src/logs/pcp_parser_[python|go]/pmrep_output_*.csv
8. Move archive → /src/archive/processed/ or /src/archive/failed/
9. Delete trigger file → Re-enable Process All button
10. View results → Grafana dashboards → http://localhost:3000
```

## Parser Selection

The system provides two parser implementations with identical functionality but different performance characteristics:

### Python Parser
- **Mature Implementation**: Well-tested, stable codebase
- **Features**: Full PCP metrics processing with validation caching
- **Best For**: Standard processing, debugging, development
- **Log Location**: `/src/logs/pcp_parser_python/`
- **Trigger File**: `/src/.process_trigger_python`

### Go Parser
- **High Performance**: 6-10x faster startup, 4-5x less memory
- **Features**: Same functionality as Python parser
- **Optimizations**:
  - 10MB buffer for large CSV files (vs 64KB default)
  - Compiled binary (no interpreter overhead)
  - Concurrent processing capabilities
- **Best For**: Large archives, production environments, resource-constrained systems
- **Log Location**: `/src/logs/pcp_parser_go/`
- **Trigger File**: `/src/.process_trigger_go`

### Performance Comparison

| Metric | Python Parser | Go Parser | Improvement |
|--------|--------------|-----------|-------------|
| Startup Time | 2-3 seconds | 0.2-0.3 seconds | **6-10x faster** |
| Memory Usage | ~200-300 MB | ~50-70 MB | **4-5x less** |
| Processing Speed | Standard | Similar | Comparable |
| Docker Image Size | ~450 MB | ~280 MB | **37% smaller** |

### How to Choose

**Use Python Parser when:**
- Running in development/test environments
- Need to debug or modify processing logic
- Standard processing speed is acceptable
- Memory is not a constraint

**Use Go Parser when:**
- Processing large archives (>1GB)
- Running on resource-constrained systems
- Need faster container startup times
- Running in production environments
- Processing many small archives quickly

### Selecting Parser in Web UI

1. Open web interface at http://localhost:5000
2. Look for "Select Parser" radio buttons
3. Choose either **Python** or **Go**
4. Click "Process All Files"
5. Selected parser will process the archives
6. Button automatically disables during processing

### Parser Architecture & Data Flow

Both parsers share the same directories and InfluxDB instance but maintain separate logs:

```
┌─────────────────────┐         ┌─────────────────────┐
│  PCP Parser Python  │         │   PCP Parser Go     │
│  (pcp_parser_python)│         │  (pcp_parser_go)    │
└──────────┬──────────┘         └──────────┬──────────┘
           │                               │
           │  Watch separate triggers      │
           │  .process_trigger_python      │
           │  .process_trigger_go          │
           │                               │
           ▼                               ▼
┌──────────────────────────────────────────────────────┐
│         /src/input/raw/*.tar.xz (shared)              │
│    Only selected parser processes files               │
└──────────┬───────────────────────────┬───────────────┘
           │                           │
           ▼                           ▼
┌──────────────────────┐     ┌──────────────────────┐
│  Python Processing   │     │   Go Processing      │
│  - Extract archive   │     │  - Extract archive   │
│  - Validate metrics  │     │  - Validate metrics  │
│  - Export to Influx  │     │  - Export to Influx  │
└──────────┬───────────┘     └──────────┬───────────┘
           │                           │
           ▼                           ▼
┌──────────────────────────────────────────────────────┐
│                      InfluxDB                         │
│  bucket: pcp-metrics                                  │
│  measurement: pcp_metrics                             │
│  tags: product_type, serialNumber                     │
└──────────────────────────────────────────────────────┘
```

**Key Differences:**

| Setting | Python Parser | Go Parser |
|---------|--------------|-----------|
| **Container Name** | `pcp_parser_python` | `pcp_parser_go` |
| **Log Directory** | `/src/logs/pcp_parser_python/` | `/src/logs/pcp_parser_go/` |
| **Metrics CSV** | `pcp_parser_python/metrics_labels.csv` | `pcp_parser_go/metrics_labels.csv` |
| **Parser Logs** | `pcp_parser_python/pcp_parser.log` | `pcp_parser_go/pcp_parser.log` |
| **CSV Output** | `pcp_parser_python/pmrep_output_*.csv` | `pcp_parser_go/pmrep_output_*.csv` |
| **Trigger File** | `/src/.process_trigger_python` | `/src/.process_trigger_go` |
| **Validation Cache** | Separate cache | Loads from Python cache as fallback |

**Shared Resources:**

| Resource | Shared? | Notes |
|----------|---------|-------|
| **Input Directory** | ✅ Yes | `/src/input/raw/` - Both read from here |
| **Processed Directory** | ✅ Yes | `/src/archive/processed/` - Files moved after processing |
| **Failed Directory** | ✅ Yes | `/src/archive/failed/` - Failed archives |
| **InfluxDB** | ✅ Yes | Same bucket, measurement, tags |
| **Trigger Files** | ❌ No | Separate triggers per parser |
| **Log Directory** | ❌ No | Separate logs prevent conflicts |

**Processing Behavior:**

When you click "Process All Files" in the web UI:

1. ✅ Web UI creates parser-specific trigger file (`.process_trigger_python` or `.process_trigger_go`)
2. ✅ **Only the selected parser** detects its trigger file
3. ✅ Selected parser removes the trigger file and starts processing
4. ✅ Parser processes ALL files in `/src/input/raw/`
5. ✅ Parser moves processed files to `/src/archive/processed/`
6. ✅ Data is written to InfluxDB
7. ✅ Process All button re-enables when trigger file is deleted

**Important:** Only one parser processes at a time, determined by your radio button selection in the web UI.

## Usage

### Adding PCP Archives

**Method 1: Web Interface (Recommended)**
1. Open http://localhost:5000
2. Drag and drop `.tar.xz` files onto the upload area
3. Click "Process All Files" to start processing
4. Monitor progress in real-time

**Method 2: Manual Copy**
1. Place your `.tar.xz` PCP archive files in:
   ```
   src/input/raw/
   ```
2. Click "Process All Files" in web interface

The parser will:
- Extract and validate metrics using cached validation
- Apply category filters (process/disk/memory/etc)
- Export to InfluxDB with async batch writes (field-based model)
- Save CSV files to logs directory
- Track metrics in metrics_labels.csv
- **Move** successfully processed archives to `archive/processed/`
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

**Method 1: Web Interface (Recommended)**
- Open http://localhost:5000
- View file statistics
- Click "Watch" on log files for live viewing
- Monitor processing status in real-time

**Method 2: Command Line**
```bash
# View parser logs (live)
tail -f src/logs/pcp_parser/pcp_parser.log

# View container logs
docker logs pcp_parser

# Check processed archives
ls -la src/archive/processed/

# Check failed archives
ls -la src/archive/failed/

# View CSV output
ls -la src/logs/pcp_parser/pmrep_output_*.csv
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

## Recent Fixes

### Fixed: Duplicate Logging (2025-01-13)
**Issue**: All log messages appeared 3 times in pcp_parser logs

**Cause**: `setup_logging()` function was called multiple times, each time adding new handlers to the root logger without clearing old ones

**Solution**: Added `logger.handlers.clear()` before adding new handlers in `setup_logging()` function

### Fixed: Configuration Not Being Used (2025-01-13)
**Issue**: Parser using default values (SERVER1/1234) instead of web UI configured values, even after container restart

**Cause**:
- Python script copied into container at build time, not runtime
- Configuration was read from environment variables at container startup, not from dynamically updated .env file

**Solution**:
1. Created `load_config_from_env_file()` function that reads from `/src/.env` file
2. Called this function in both `main()` and `process_all_archives()` to load config dynamically
3. Added logging to show what tags are being used: "DATA TAGGING CONFIGURATION"
4. **Important**: Container must be rebuilt (not just restarted) when Python code changes

**How to Apply Config Changes**:
```bash
# Option 1: Use web UI (recommended)
- Update config in web UI
- Click "Update Configuration"
- Web UI automatically rebuilds and restarts pcp_parser container

# Option 2: Manual rebuild
cd src
docker-compose build pcp_parser
docker-compose up -d pcp_parser
```

### Fixed: Grafana Variables Not Working (2025-01-13)
**Issue**: Dashboard variables showing errors or not populating from InfluxDB

**Solution**: Updated variable queries to use `v1.tagValues()` format:
```flux
import "influxdata/influxdb/v1"
v1.tagValues(bucket: "pcp-metrics", tag: "product_type", start: -30d)
```

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
- ✅ **Hierarchical organization** by metric category (12 top-level groups)
- ✅ **Collapsible rows** - clean interface, expand only what you need
- ✅ **2,652 metrics** organized into 74 subcategories
- ✅ **Field-based queries** with ANY/ANY default filters
- ✅ **Auto-updates** when dashboard is regenerated

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
[NETWORK] - 10 subcategories, 1315 metrics
[PSOC] - 4 subcategories, 312 metrics
... and 6 more groups (filesys, hinv, ipc, swapdev, vfs, xfs)
```

**Dashboard Variables**:
- **product_type**: Default "All" - dynamically populated from InfluxDB tags
- **serialNumber**: Default "All" - dynamically populated from InfluxDB tags
- Variables auto-discover unique values from your data
- Queries use regex matching (=~) to support "All" option
- Select specific values to filter dashboard data

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
  - Template variable defaults (currently: ANY/ANY)

**Note**: Dashboard uses field-based queries with proper regex syntax (no escaped underscores).

See `src/grafana/DASHBOARD_README.md` for detailed documentation.

## Metric Validation System

### Overview

The parser uses a two-stage validation system to ensure only valid, numeric time-series metrics are exported to InfluxDB.

### Why Validation is Necessary

PCP archives contain ~1,976 metric definitions, but not all are suitable for time-series storage:

| Metric Type | Example | Why Invalid | Count |
|-------------|---------|-------------|-------|
| **String metrics** | `pmcd.hostname` | Returns text like "server01", not numbers | ~15 |
| **Event metrics** | `event.flags` | Event tracing, not time-series numeric data | ~8 |
| **Derived metrics** | Computed metrics | No raw data stored (PM_ERR_VALUE) | ~12 |
| **Empty instances** | `proc.psinfo.*` | Per-process metrics but no processes logged | ~25 |
| **No data** | Various | Defined but never collected in archive | ~20 |
| **Type errors** | Various | Wrong data type for numeric export | ~8 |
| **Other errors** | Various | PM_ERR_* errors from PCP | ~6 |
| **Total filtered** | | | **~94** |
| **Valid metrics** | | Numeric time-series data | **1,882** |

### The Validation Process

#### **Stage 1: Discovery (pminfo)**

```bash
pminfo -a /archive/20251009
```

**Output:** List of all 1,976 metric names from archive metadata

**Example:**
```
kernel.all.load        ✅ Numeric time-series
mem.freemem            ✅ Numeric gauge
pmcd.hostname          ❌ String (will fail validation)
event.flags            ❌ Event type (will fail validation)
disk.dev.read          ✅ Numeric counter
proc.psinfo.utime      ⚠️  May have no instances
```

#### **Stage 2: Validation Test (pmrep batch testing)**

Each metric is tested to verify it can return numeric CSV data:

```bash
# Test command for each metric
pmrep -a /archive/20251009 -s 1 -o csv --ignore-unknown <metric_name>
```

**Valid Metric Example:**
```bash
$ pmrep -a archive -s 1 -o csv kernel.all.load
Time,kernel_all_load
2025-10-09 12:00:00,1.23
```
✅ **Result:** Returns numeric data → Added to `validated_metrics.txt`

**Invalid Metric Example:**
```bash
$ pmrep -a archive -s 1 -o csv pmcd.hostname
(empty output or PM_ERR_TYPE)
```
❌ **Result:** No numeric data → Filtered out

**Batch Optimization:**
- Metrics tested in batches of 100 (configurable via `VALIDATION_BATCH_SIZE`)
- If entire batch succeeds → all 100 added to valid list
- If batch fails → test each individually to find invalid ones
- **Time:** 76-227 seconds (Python: 216s, Go: 76s, Rust: 227s)

#### **Stage 3: Category Filtering**

After validation, apply user-configured category filters:

```
1,882 validated metrics
  - Remove proc.* if ENABLE_PROCESS_METRICS=false (6 metrics)
  - Remove swap.* if ENABLE_SWAP_METRICS=false (7 metrics)
  - Remove nfs.* if ENABLE_NFS_METRICS=false (varies)
  = 1,869 final metrics saved to validated_metrics.txt
```

### The Cache File: `validated_metrics.txt`

**Location:** `src/logs/pcp_parser_*/validated_metrics.txt` (per parser)

**Format:** Simple newline-separated list of metric names
```
pmda.uname
xfs.log.writes
kernel.all.load
mem.freemem
disk.dev.read
network.interface.in.bytes
...
(1,869 total)
```

**Purpose:** Performance cache to avoid re-validating metrics on every archive

**Behavior:**
- **First run:** File doesn't exist → Full validation (76-227s) → Create cache
- **Subsequent runs:** File exists → Load cache (0.01s) → Skip validation
- **Missing/corrupted:** Auto-regenerates on next run
- **Force refresh:** Set `FORCE_REVALIDATE=true`

### Performance Impact

| Scenario | Validation Time | Export Time | Total Time |
|----------|----------------|-------------|------------|
| **First run (no cache)** | 76-227s | 180-360s | 4-10 min |
| **Cached runs** | 0.01s | 180-360s | 3-6 min |
| **Speedup** | **200x faster** | Same | **20-30% faster overall** |

**With SKIP_VALIDATION=true (not recommended):**
- Validation: 0s (skipped)
- Export: 200-400s (slower - queries 94 invalid metrics)
- Result: Larger CSV files, more empty values, potential errors

### Configuration Options

#### **SKIP_VALIDATION** (⚠️ Not Recommended)
```yaml
- SKIP_VALIDATION=false  # Default: validate metrics
- SKIP_VALIDATION=true   # RISKY: use all metrics without validation
```

**What it does:**
- `false`: Test metrics with pmrep, filter out invalid ones (recommended)
- `true`: Skip validation, use all 1,976 metrics including 94 invalid ones

**Why you shouldn't skip:**
- Wastes CPU querying metrics that return no data
- Larger CSV files with empty columns
- More "empty/invalid values skipped" warnings
- Slightly slower pmrep execution

#### **FORCE_REVALIDATE**
```yaml
- FORCE_REVALIDATE=false  # Default: use cache if available
- FORCE_REVALIDATE=true   # Force re-validation, ignore cache
```

**When to use:**
- After upgrading PCP version
- After changing category filters (ENABLE_*_METRICS)
- When archive format changes
- Troubleshooting validation issues
- Testing new metric configurations

**After running once with `FORCE_REVALIDATE=true`, set it back to `false` for normal operation.**

#### **VALIDATION_BATCH_SIZE**
```yaml
- VALIDATION_BATCH_SIZE=100   # Default: balanced
- VALIDATION_BATCH_SIZE=200   # Faster validation
- VALIDATION_BATCH_SIZE=50    # Slower, more granular error detection
```

**How it works:**
- Tests N metrics together with single pmrep command
- Larger batches = fewer pmrep calls = faster validation
- Smaller batches = better error isolation = slower validation

### Validation Workflow

```
START: Process Archive
    ↓
Does validated_metrics.txt exist?
    ↓
    NO → Full Validation (76-227s)
         ├─ pminfo → discover 1,976 metrics
         ├─ pmrep batch test → validate each metric
         ├─ Filter out 94 invalid metrics
         ├─ Apply category filters → 1,869 metrics
         ├─ Save to validated_metrics.txt
         └─ Continue to export
    ↓
    YES → Load Cache (0.01s)
         ├─ Read 1,869 metric names from file
         └─ Continue to export
    ↓
Export with pmrep
    ├─ Query only validated 1,869 metrics
    ├─ Generate CSV with numeric data
    └─ Write to InfluxDB
    ↓
END: Archive processed
```

### Troubleshooting

**No validated_metrics.txt file:**
- Normal on first run
- Auto-created after validation
- If missing later, auto-regenerates on next archive

**0 metrics validated:**
- Check archive is valid: `pminfo -a /path/to/archive`
- Try `FORCE_REVALIDATE=true` to rebuild cache
- Check logs for PM_ERR_* errors

**Too many metrics filtered:**
- Review category filters (ENABLE_*_METRICS settings)
- Check if archive has unusual metric mix
- Verify PCP version compatibility

**Validation takes too long:**
- Increase `VALIDATION_BATCH_SIZE` to 200-500
- Only happens once, cached for all future archives
- Go parser is 3x faster than Python (76s vs 216s)

## Performance Tuning

The PCP parser includes configurable performance parameters for optimal processing speed.

### Current Performance

**Processing Speed** (with validation cache):

| Parser | First Run (with validation) | Cached Runs | Total for 4 Archives |
|--------|---------------------------|-------------|----------------------|
| **Python** | 6m 55s | 1m 34s | 14m 40s |
| **Go** | 4m 17s | 1m 19s | 10m 42s (27% faster) |
| **Rust** | 6m 59s | 1m 26s | 14m 5s |

**Speedup with cache:** 200x faster validation (0.01s vs 76-227s)

### Configuration Parameters

All parameters are configurable via environment variables in `docker-compose.yml`:

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
