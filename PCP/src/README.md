# PCP Metrics Processing System - Source Code

## Overview

This directory contains all source code for the PCP (Performance Co-Pilot) metrics processing system. The system processes PCP archive files, extracts metrics, and exports them to:

- **InfluxDB** - Time-series database for real-time metrics and Grafana dashboards
- **AWS S3 Parquet** *(optional)* - Cloud storage in columnar format for long-term analytics via AWS Athena

Both export options can be used simultaneously or independently.

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Docker Compose Network                        │
│                          (pcp-network)                               │
└─────────────────────────────────────────────────────────────────────┘

┌──────────────┐  HTTP:5000   ┌──────────────────────────────────────┐
│ Web Control  │◄─────────────┤         User Browser                  │
│    Panel     │              │  - Upload archives                    │
│ (Flask App)  │              │  - Trigger processing                 │
│              │              │  - View logs/CSV                      │
└──────┬───────┘              └──────────────────────────────────────┘
       │
       │ Creates trigger files
       │ (.process_trigger_python/go/rust)
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Parser Containers                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
│  │   Python     │  │     Go       │  │    Rust      │             │
│  │   Parser     │  │   Parser     │  │   Parser     │             │
│  │              │  │              │  │              │             │
│  │  - Extract   │  │  - Extract   │  │  - Extract   │             │
│  │  - Validate  │  │  - Validate  │  │  - Validate  │             │
│  │  - Transform │  │  - Transform │  │  - Transform │             │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘             │
└─────────┼──────────────────┼──────────────────┼────────────────────┘
          │                  │                  │
          │                  │                  │
          └──────────────────┴──────────────────┘
                             │
                ┌────────────┴────────────┐
                │                         │
                │ Write points            │ Export Parquet (optional)
                ▼                         ▼
       ┌─────────────────┐      ┌──────────────────┐
       │    InfluxDB     │      │    AWS S3        │
       │   (Port 8086)   │      │                  │
       │                 │      │  - Parquet files │
       │  - Time-series  │      │  - Partitioned   │
       │  - Bucket: pcp  │      │  - Athena query  │
       │  - Org: pcp-org │      └────────┬─────────┘
       └────────┬────────┘               │
                │                        │
                │ Query data             │ Query via Athena
                ▼                        │
       ┌─────────────────┐      ┌────────────────┐
       │    Grafana      │◄─────┤  User Browser  │
       │   (Port 3000)   │      │ - View metrics │
       │                 │      │ - Dashboards   │
       │ - InfluxDB DS   │      └────────────────┘
       │ - Athena DS     │
       └─────────────────┘
```

### Data Flow

```
1. PCP Archive Upload
   ┌─────────────────┐
   │ .tar.xz Archive │  → /src/input/raw/
   └─────────────────┘

2. Processing Trigger
   User clicks "Process All Files" → Creates .process_trigger_[parser]

3. Archive Processing
   ┌──────────────┐
   │  Extract     │  → Decompress .tar.xz
   │  Archive     │     Find .meta file (PCP archive base)
   └──────┬───────┘
          │
   ┌──────▼───────┐
   │  Validate    │  → pminfo: discover metrics
   │  Metrics     │     Load validated_metrics.txt
   │              │     OR validate each metric with pmrep
   └──────┬───────┘
          │
   ┌──────▼───────┐
   │  Extract     │  → pmrep: export to CSV
   │  Data        │     Parse CSV rows
   └──────┬───────┘
          │
   ┌──────▼───────┐
   │  Transform   │  → Create InfluxDB points
   │  & Export    │     Batch write (50k-200k points)
   │              │     Field-based data model
   └──────┬───────┘
          │
   ┌──────▼───────┐
   │  Archive     │  → Success: /src/archive/processed/
   │  Management  │     Failed:  /src/archive/failed/
   └──────────────┘

4. Visualization
   Grafana → Query InfluxDB → Display dashboards
```

### Container Architecture

| Container | Base Image | Purpose | Port | Dependencies |
|-----------|------------|---------|------|--------------|
| **influxdb** | influxdb:2.7-alpine | Time-series database | 8086 | None |
| **grafana** | grafana/grafana:latest | Visualization | 3000 | influxdb |
| **pcp_parser_python** | Ubuntu 22.04 + PCP | Archive processing | - | influxdb |
| **pcp_parser_go** | Ubuntu 22.04 + PCP | Archive processing | - | influxdb |
| **pcp_parser_rust** | Ubuntu 22.04 + PCP | Archive processing | - | influxdb |
| **web_pcp_ctrl** | Python 3.11 + Flask | Web interface | 5000 | None |

### Communication Patterns

1. **HTTP APIs**
   - Web UI → InfluxDB: Health checks
   - Grafana → InfluxDB: Flux queries
   - Web UI → Parsers: File triggers

2. **Shared Volumes**
   - `/src` - Mounted in all containers
   - `/src/input/raw` - Shared archive input
   - `/src/logs` - Separate logs per parser
   - `/src/archive` - Shared processed/failed directories

3. **Docker Network**
   - Bridge network: `pcp-network`
   - Service discovery by container name
   - Internal DNS resolution

## Directory Structure

```
src/
├── docker-compose.yml           # Main orchestration file
├── .env                        # Configuration (product type, serial number)
│
├── pcp_parser/                 # PCP Parser (Python implementation)
│   ├── Dockerfile
│   ├── pcp_parser.py          # Main parser (1668 lines)
│   └── README.md
│
├── web_pcp_ctrl/              # Web Control Panel
│   ├── Dockerfile
│   ├── app.py                 # Flask backend (551 lines)
│   └── templates/
│       └── index.html         # Web UI
│
├── grafana/                   # Grafana dashboards & generators
│   ├── generate_dashboard.py        # Auto dashboard generator (332 lines)
│   ├── generate_limited_dashboard.py # Limited view generator (296 lines)
│   ├── update_dashboard.py          # Dashboard updater (35 lines)
│   └── provisioning/
│       ├── datasources/
│       └── dashboards/
│
├── input/                     # Input files
│   ├── raw/                   # PCP archives (.tar.xz)
│   └── data_filter/           # Metric filtering config
│       └── validated_metrics.txt
│
├── archive/                   # Archive management
│   ├── processed/             # Successfully processed
│   └── failed/                # Failed archives
│
└── logs/                      # Application logs
    ├── pcp_parser_python/
    ├── pcp_parser_go/
    ├── grafana/
    └── influxdb/
```

## Component Details

### 1. PCP Parsers

Three implementations with identical functionality:

| Parser | Language | Main File | Lines | Use Case |
|--------|----------|-----------|-------|----------|
| Python | Python 3 | `pcp_parser/pcp_parser.py` | 1,668 | Development, debugging |
| Go | Go 1.21+ | `pcp_parser_go/main.go` | ~800 | Production, performance |
| Rust | Rust 1.70+ | `pcp_parser_rust/src/main.rs` | ~900 | Experimental |

**Processing Pipeline:**

**Overview:** `.tar.xz` archive → Extract → Validate → Export (pmrep CSV) → **Convert to InfluxDB Points** → Write to InfluxDB

```
PHASE 1: ARCHIVE EXTRACTION [SERIAL]
└─> tarfile.extractall() → /tmp/pcp_archives/
    Find .meta file (PCP archive identifier)
    [One archive at a time]

PHASE 2: METRIC VALIDATION [PARALLEL]
├─> Load validated_metrics.txt (if exists) → 0.01s (cached)
OR
└─> pminfo -a <archive> → discover all metrics (~2000)
    └─> Parallel validation (100 workers)
        └─> Filter invalid/derived metrics (proc.*, nfs.*, etc.)
        └─> Save to validated_metrics.txt
    [ThreadPoolExecutor with 100 workers - always parallel]

PHASE 3: DATA EXPORT - 2 PROCESSING MODES
(Mode automatically selected based on pandas availability)

┌─────────────────────────────────────────────────────────────────┐
│ MODE A: PANDAS (Default when pandas installed)                 │
│ Automatically uses memory buffer for vectorized processing     │
└─────────────────────────────────────────────────────────────────┘
   STEP 1: pmrep Data Extraction
   └─> subprocess.Popen(['pmrep', '-a', archive, '-o', 'csv', metrics...])
       [STREAMING - Real-time stdout reading]

   STEP 2: CSV Processing (Memory Buffer)
   └─> Collect ALL CSV output into StringIO buffer
       [STREAMING collection, no disk I/O]

   STEP 3: InfluxDB Connection (Only if ENABLE_INFLUXDB_WRITE=true)
   └─> IF ENABLE_INFLUXDB_WRITE=true:
       ├─> Connect to InfluxDB: http://influxdb:8086
       ├─> Initialize WriteAPI with WriteOptions(batch_size=50k, async=True)
       └─> [ASYNC - Background threads for non-blocking writes]
       ELSE:
       └─> Skip connection (no InfluxDB writes)

   STEP 4: Pandas DataFrame Processing
   └─> pd.read_csv(StringIO) → DataFrame
       Vectorized column operations
       [SERIAL - Single-threaded pandas operations]

   STEP 5: Point Creation (DataFrame → InfluxDB Line Protocol)
   └─> FOR EACH ROW in DataFrame:
       ├─> Parse timestamp (YYYY-MM-DD HH:MM:SS) → UTC
       ├─> CREATE Point object:
       │   - Measurement: "pcp_metrics"
       │   - Tags: product_type={PRODUCT_TYPE}, serialNumber={SERIAL_NUMBER}
       │   - Time: timestamp
       │   - Fields: ALL metrics as separate fields
       │     (metric.name → metric_name, float values)
       └─> Apply PCP_METRICS_FILTER (skip_zero, skip_empty, skip_none)
       [SERIAL - Row-by-row conversion to InfluxDB format]

   STEP 6: Output Destination (Based on flags)
   └─> IF ENABLE_INFLUXDB_WRITE=true:
       ├─> Batch writes every 50,000 points
       ├─> write_api.write(bucket=INFLUXDB_BUCKET, record=points)
       └─> [ASYNC - Background threads, non-blocking, gzip, retry]
       IF SAVE_CSV_OUTPUT=true:
       └─> Also save to CSV file
       ELSE (neither flag enabled):
       └─> Process data only (dry-run mode)
       [Progress logged every 50 batches]

   STEP 7: Flush Async Writes (Only if ENABLE_INFLUXDB_WRITE=true)
   └─> IF write_api exists:
       ├─> write_api.flush() → Wait for all background writes
       └─> [BLOCKING - Ensures all data written before proceeding]

┌─────────────────────────────────────────────────────────────────┐
│ MODE B: STREAMING (Automatic fallback)                         │
│ Used when pandas not available - line-by-line processing       │
└─────────────────────────────────────────────────────────────────┘
   Steps 1-2: Same as MODE A

   STEP 3-5: COMBINED Streaming CSV Processing
   └─> FOR EACH LINE from pmrep stdout:
       ├─> Parse CSV line immediately (no buffering)
       ├─> Parse timestamp
       ├─> CREATE Point object with tags and fields
       └─> Append to batch (50k point batches)
       [STREAMING - Line-by-line, minimal memory]

   STEP 6-7: Same as MODE A

PHASE 4: ARCHIVE MANAGEMENT [SERIAL]
├─> Success → Move to /src/archive/processed/
└─> Failure → Move to /src/archive/failed/
```

### Metrics Files

The parser uses two important files for metric management:

#### `validated_metrics.txt`
**Location**: `/src/input/data_filter/validated_metrics.txt`

**Purpose**: Cache of validated metric names to speed up processing

**Format**:
```
kernel.all.cpu.idle
kernel.all.cpu.user
mem.util.used
mem.util.free
disk.dev.read
disk.dev.write
...
```

**Behavior**:
- **If file exists**: Parser loads metrics from file (instant, ~0.01s)
- **If file missing**: Parser validates all metrics using pmrep (slow, ~30s for 2000 metrics)
- **Auto-generated**: Created automatically after first validation
- **Category filtering**: Metrics filtered based on `ENABLE_*_METRICS` flags before saving

**When to delete**:
- When you want to re-validate all metrics (`FORCE_REVALIDATE=true` does this automatically)
- When PCP version changes
- When archive format changes

#### `metrics_labels.csv`
**Location**: `/src/logs/pcp_parser_python/metrics_labels.csv`

**Purpose**: Track which metrics have been successfully processed

**Format**:
```csv
metric_name
kernel.all.cpu.idle
kernel.all.cpu.user
mem.util.used
...
```

**Behavior**:
- **Updated during processing**: Each successfully processed metric is added
- **Cumulative**: Grows over time as different archives are processed
- **Used for**: Debugging, metric coverage analysis, dashboard generation

**Usage**:
```bash
# Count unique metrics processed
wc -l /src/logs/pcp_parser_python/metrics_labels.csv

# Check if specific metric was processed
grep "kernel.all.cpu" /src/logs/pcp_parser_python/metrics_labels.csv
```

**Key Point Conversion Details:**

Each CSV row is converted into a **single InfluxDB Point** with:
- **Measurement**: `pcp_metrics` (fixed for all data)
- **Tags** (indexed, low cardinality):
  - `product_type`: From .env (e.g., "SERVER1")
  - `serialNumber`: From .env (e.g., "1234")
- **Fields** (values, high cardinality):
  - ALL PCP metrics as separate fields
  - Field naming: `metric.name` → `metric_name` (dots to underscores)
  - Type: float64 for all values
  - Example: `kernel_all_cpu_idle=95.2, mem_util_free=4096000000`
- **Timestamp**: From CSV first column (UTC)

**InfluxDB Write Control:**
- ALL InfluxDB write operations respect `ENABLE_INFLUXDB_WRITE` flag
- When `ENABLE_INFLUXDB_WRITE=false`:
  - Points are created and processed normally
  - Writes are skipped (dry-run mode for testing)
  - Logs show "processed (not written)" status
- When `ENABLE_INFLUXDB_WRITE=true`:
  - Normal async batched writes to InfluxDB
  - Gzip compression and retry logic enabled

**Current Configuration (docker-compose.yml) - SIMPLIFIED:**
```yaml
# Essential flags only (simplified from 10+ flags to 3)
SAVE_CSV_OUTPUT=true            # Save CSV files for debugging
ENABLE_INFLUXDB_WRITE=true      # Write to InfluxDB (set false to test)
INFLUX_BATCH_SIZE=50000         # Write 50k points per batch
```

**Processing Modes (Automatic Selection):**
- **Pandas Mode** (when pandas installed): Vectorized processing with memory buffer
- **Streaming Mode** (when pandas unavailable): Line-by-line processing (lower memory)

**Parallel/Serial/Async Summary:**

| Stage | Type | Implementation | Notes |
|-------|------|----------------|-------|
| Extraction | Serial | `tarfile.extractall()` | One archive at a time |
| Validation | **Parallel** | `ThreadPoolExecutor(100)` | Always parallel for performance |
| pmrep Process | Serial | `subprocess.Popen` | Single process per archive |
| CSV Collection | Streaming | `for line in stdout:` | Real-time collection to memory |
| Pandas Processing | Serial | `pd.read_csv()` | Vectorized DataFrame ops (if available) |
| Point Creation | Serial | Loop per row | Create Point/LineProtocol |
| InfluxDB Writes | **ASYNC** | Background threads | Non-blocking, gzip, retry |
| Write Flush | Blocking | `write_api.flush()` | Wait for all writes |
| sname Processing | Parallel | Separate thread | If `ENABLE_SNAME_PROCESSING=true` |

**Key Functions:**
- `process_archive()` - Main processing loop
- `get_available_metrics()` - Metric discovery/validation
- `export_to_influxdb()` - Data transformation and export
- `load_validated_metrics_cache()` - Cache management

**Export Options:**
- **InfluxDB**: Primary time-series database for Grafana dashboards
- **AWS S3 Parquet** *(optional)*: Long-term cloud storage with Athena query support

See [pcp_parser/README.md](pcp_parser/README.md#aws-s3-parquet-export) for AWS S3 configuration.

### 2. Web Control Panel

**File:** `web_pcp_ctrl/app.py` (551 lines)

**Flask Routes:**
```python
GET  /                          # Main UI
GET  /api/files/input           # List input files
GET  /api/files/processed       # List processed files
GET  /api/files/failed          # List failed files
GET  /api/logs                  # List log files
GET  /api/csv                   # List CSV files
POST /api/upload                # Upload archive
POST /api/process               # Trigger processing
POST /api/config                # Update configuration
DELETE /api/delete/input/<file> # Delete files
```

**Features:**
- File management (upload, delete, list)
- Processing triggers via file creation
- Log viewing with live streaming
- Configuration management (.env)
- Docker container restart

### 3. Grafana Dashboard Generators

#### Auto Dashboard Generator

**File:** `grafana/generate_dashboard.py` (332 lines)

**Function:** Generate dashboard from all discovered metrics

**Process:**
```python
1. Load metrics from metrics_labels.csv
2. Categorize by prefix (disk.*, kernel.*, mem.*)
3. Create hierarchical structure (12 groups, 74 subcategories)
4. Generate panels (10 metrics per panel)
5. Create collapsible rows
6. Write to provisioning/dashboards/json/pcp-auto-dashboard.json
```

**Usage:**
```bash
cd src/grafana
python generate_dashboard.py
```

**Output:**
- Dashboard UID: `pcp-auto-metrics`
- URL: `http://localhost:3000/d/pcp-auto-metrics`
- Auto-reloads in Grafana within 30 seconds

#### Limited View Generator

**File:** `grafana/generate_limited_dashboard.py` (296 lines)

**Function:** Generate curated dashboard from validated_metrics.txt

**Process:**
```python
1. Load input/data_filter/validated_metrics.txt
2. Parse category headers (## comments)
3. Group metrics by category
4. Create focused panels (~10 metrics each)
5. Write to provisioning/dashboards/json/pcp-limited-view.json
```

**Usage:**
```bash
cd src/grafana
python generate_limited_dashboard.py
```

**Output:**
- Dashboard UID: `pcp-limited-view`
- URL: `http://localhost:3000/d/pcp-limited-view`
- Curated view with ~100 essential metrics

#### Dashboard Updater

**File:** `grafana/update_dashboard.py` (35 lines)

**Function:** Update existing dashboard for ANY/ANY variable support

**Process:**
```python
1. Load dashboard JSON
2. Find all panel queries
3. Replace exact filters with regex (=~ /pattern/)
4. Update nested panels recursively
5. Save modified JSON
```

**Usage:**
```bash
cd src/grafana
python update_dashboard.py
```

### Dashboard Generation Workflow

```
Metric Discovery (Parser)
    ↓
metrics_labels.csv
    ↓
    ├─→ Auto Dashboard Generator → pcp-auto-dashboard.json
    │   (All discovered metrics)
    │
    └─→ Limited View Generator → pcp-limited-view.json
        (Curated metrics only)
            ↓
    Dashboard Updater (optional)
        Update filters for ANY/ANY
            ↓
    Grafana Auto-Provisioning
        Loads dashboards within 30s
```

## Configuration Management

### Environment Variables

All components use environment variables for configuration:

```yaml
# Directories
WATCH_DIR=/src/input/raw
EXTRACT_DIR=/tmp/pcp_archives
PROCESSED_DIR=/src/archive/processed
FAILED_DIR=/src/archive/failed
LOG_DIR=/src/logs/pcp_parser

# InfluxDB
INFLUXDB_URL=http://influxdb:8086
INFLUXDB_TOKEN=pcp-admin-token-12345
INFLUXDB_ORG=pcp-org
INFLUXDB_BUCKET=pcp-metrics

# Data Tagging
PRODUCT_TYPE=SERVER1
SERIAL_NUMBER=1234

# Performance Tuning
VALIDATION_BATCH_SIZE=100
INFLUX_BATCH_SIZE=50000
PROGRESS_LOG_INTERVAL=50

# Feature Flags
SKIP_VALIDATION=false
FORCE_REVALIDATE=false
ENABLE_PROCESS_METRICS=false
SAVE_CSV_OUTPUT=true

# Export Options
ENABLE_INFLUXDB_WRITE=true     # Write to InfluxDB
ENABLE_S3_EXPORT=false         # Write to AWS S3 Parquet (optional)

# S3 Configuration (if ENABLE_S3_EXPORT=true)
S3_BUCKET_NAME=pcp-metrics-parquet
S3_KEY_PREFIX=time-series-data/
AWS_REGION=us-east-1
PARQUET_COMPRESSION=snappy
# S3 Partitioning: product_type/serial_number/year/month/day/hour/
```

### Configuration Files

1. **`.env`** - Data tagging (product type, serial number)
2. **`docker-compose.yml`** - Service configuration
3. **`validated_metrics.txt`** - Metric whitelist
4. **`grafana.ini`** - Grafana settings

## Development Workflow

### Adding New Metrics

1. Edit `input/data_filter/validated_metrics.txt`
2. Add metric names (one per line)
3. Optional: Add category headers with `##`
4. Restart parser container
5. Process archive to verify metrics

### Modifying Dashboard

**Option 1: Manual (Grafana UI)**
```
1. Edit dashboard in Grafana UI
2. Export JSON
3. Save to provisioning/dashboards/json/
4. Grafana auto-reloads within 30s
```

**Option 2: Regenerate (Script)**
```bash
# Full dashboard (all metrics)
cd src/grafana
python generate_dashboard.py

# Limited view (curated metrics)
python generate_limited_dashboard.py

# Update existing dashboard
python update_dashboard.py
```

### Debugging Parsers

**View logs:**
```bash
# Python parser
tail -f src/logs/pcp_parser_python/pcp_parser.log

# Go parser
tail -f src/logs/pcp_parser_go/pcp_parser_go.log

# Container logs
docker logs pcp_parser_python -f
```

**Common issues:**
- 0 points written → Check `SKIP_VALIDATION=false`
- Slow processing → Disable `ENABLE_PROCESS_METRICS`
- Cache not working → Verify `validated_metrics.txt` exists

### Container Management

**Rebuild parser:**
```bash
cd src
docker-compose build pcp_parser_python
docker-compose up -d pcp_parser_python
```

**Restart all services:**
```bash
docker-compose restart
```

**View container stats:**
```bash
docker stats
```

## Data Model

### InfluxDB Schema

**Measurement:** `pcp_metrics`

**Tags (indexed):**
- `product_type` - Configurable via .env
- `serialNumber` - Configurable via .env

**Fields (values):**
- All PCP metrics as separate fields
- Field names: metric.name → metric_name (dots to underscores)
- Type: float64

**Example:**
```
pcp_metrics,product_type=SERVER1,serialNumber=1234
  kernel_all_cpu_idle=95.2,
  kernel_all_cpu_user=3.1,
  mem_util_free=4096000000
  1699876543000000000
```

**Benefits:**
- Low cardinality (2 tags vs thousands)
- Single point per timestamp
- Efficient field regex queries
- Scales to thousands of metrics

### Metric Validation

**File:** `input/data_filter/validated_metrics.txt`

**Format:**
```
## Category Name (optional header)
metric.name.one
metric.name.two

## Another Category
other.metric.name
```

**Behavior:**
- File exists → Use these metrics (0.01s load)
- File missing → Auto-discover and validate (76-227s)
- Comments (##) → Used for organization, ignored by parser

## Performance

### Parser Comparison

| Metric | Python | Go | Rust |
|--------|--------|-----|------|
| Startup | 2-3s | 0.2-0.3s | 0.3-0.4s |
| Memory | 200-300 MB | 50-70 MB | 40-60 MB |
| Validation | 216s | 76s | 227s |
| Processing (cached) | 94s | 79s | 86s |
| Total (4 archives) | 14m 40s | 10m 42s | 14m 5s |

### Performance Settings

```yaml
# High throughput configuration
VALIDATION_BATCH_SIZE=500        # Larger batches
INFLUX_BATCH_SIZE=200000         # More points per write
SAVE_CSV_OUTPUT=false            # Skip CSV write
ENABLE_PROCESS_METRICS=false     # Avoid high cardinality

# Low memory configuration
VALIDATION_BATCH_SIZE=100
INFLUX_BATCH_SIZE=50000
SAVE_CSV_OUTPUT=false
```

## Troubleshooting Guide

### Common Issues

1. **0 Data Points Written**
   - Check `SKIP_VALIDATION=false`
   - Verify metrics in validated_metrics.txt
   - Review value filters

2. **Slow Processing**
   - Disable process metrics (`ENABLE_PROCESS_METRICS=false`)
   - Increase batch sizes
   - Use Go parser
   - Enable validation cache

3. **High Memory Usage**
   - Reduce batch sizes
   - Set `SAVE_CSV_OUTPUT=false` to reduce memory
   - Limit metric count with category filters

4. **Connection Errors**
   - Check InfluxDB health
   - Verify network connectivity
   - Review credentials
   - Check firewall rules

## File Reference

### Key Files

| File | Purpose | Modified By |
|------|---------|-------------|
| `docker-compose.yml` | Service orchestration | Manual |
| `.env` | Data tagging config | Web UI |
| `input/data_filter/validated_metrics.txt` | Metric whitelist | Manual |
| `logs/pcp_parser_*/pcp_parser.log` | Parser logs | Parser |
| `logs/pcp_parser_*/metrics_labels.csv` | Discovered metrics | Parser |
| `archive/processed/` | Successful archives | Parser |
| `archive/failed/` | Failed archives | Parser |
| `grafana/provisioning/dashboards/json/*.json` | Dashboard definitions | Generator scripts |

### Log Files

```
logs/
├── pcp_parser_python/
│   ├── pcp_parser.log              # Processing logs
│   ├── metrics_labels.csv          # All discovered metrics
│   ├── validated_metrics_discovered.txt  # Auto-discovered metrics
│   └── pmrep_output_*.csv          # Raw CSV exports
├── pcp_parser_go/
│   └── pcp_parser_go.log
├── pcp_parser_rust/
│   └── pcp_parser_rust.log
├── grafana/
│   └── grafana.log
└── influxdb/
    └── influxdb.log
```

## Related Documentation

- [Main Project README](../README.md) - Complete system documentation
- [Performance Tuning Guide](PERFORMANCE_TUNING.md) - Performance configuration
- [Dashboard Documentation](grafana/DASHBOARD_README.md) - Dashboard details
- [Directory Structure](DIRECTORY_STRUCTURE.md) - Full directory layout
