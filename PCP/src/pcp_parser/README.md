# PCP Parser

Python-based parser for Performance Co-Pilot (PCP) archives that exports metrics to InfluxDB for visualization in Grafana.

## Table of Contents

- [Overview](#overview)
- [Parser Implementations](#parser-implementations)
- [Features](#features)
- [Quick Start](#quick-start)
- [Parser Configuration](#parser-configuration)
  - [Configuration File](#configuration-file-env)
  - [Common Configurations](#common-configurations)
  - [Stopping Parsers](#stopping-parsers)
  - [Viewing Logs](#viewing-logs)
  - [Rebuilding Parsers](#rebuilding-parsers)
  - [Parser Architecture](#parser-architecture)
  - [Best Practices](#best-practices)
- [Configuration](#configuration)
- [Process Metrics](#process-metrics)
- [Performance Optimization](#performance-optimization)
- [InfluxDB Schema](#influxdb-schema)
- [Logging](#logging)
- [Sample Archives](#sample-archives)
- [Troubleshooting](#troubleshooting)
- [Quick Reference](#quick-reference)
- [Usage Examples](#usage-examples)

---

## Overview

The PCP Parser reads Performance Co-Pilot archive files and exports system metrics to InfluxDB. It supports:
- Standard system metrics (CPU, memory, disk, network)
- Process state metrics (`proc.psinfo.sname`)
- Parallel processing for optimal performance
- Flexible filtering and configuration
- CSV export option

---

## Parser Implementations

The PCP monitoring system supports **three parser implementations**:

| Feature | Python | Go | Rust |
|---------|--------|----|----|
| **Stability** | ✓✓✓ High | ✓✓ Medium | ✓ Low |
| **Performance** | ✓ 1x baseline | ✓✓✓ 3-5x faster | ✓✓✓ 3-5x faster |
| **Memory Usage** | ✓✓ Medium | ✓✓✓ Low | ✓✓✓ Very Low |
| **Features** | ✓✓✓ Complete | ✓✓ Most | ✓ Basic |
| **Maintenance** | ✓✓✓ Active | ✓✓ Active | ✓ Experimental |
| **Production Ready** | ✓✓✓ Yes | ✓ Beta | ✗ No |

**Default**: Only the **Python parser runs** by default. You can enable/disable parsers via configuration (see [Parser Configuration](#parser-configuration)).

---

## Features

### Core Capabilities
- **Multi-metric support**: Processes validated metrics from configuration file
- **InfluxDB integration**: Direct export to InfluxDB v2 with proper schema
- **CSV export**: Optional CSV output for offline analysis
- **Parallel processing**: Process metrics in parallel for 30-50% faster execution
- **Process state tracking**: Monitor running, blocked, zombie, and stopped processes
- **Comprehensive logging**: Detailed statistics and progress tracking

### Process State Monitoring
The parser can track process states including:
- **Running (R)**: Processes actively using CPU
- **Blocked (D)**: Processes waiting for I/O (potential bottlenecks)
- **Sleeping (S)**: Idle processes waiting for events
- **Idle (I)**: Idle kernel threads
- **Zombie (Z)**: Terminated processes not reaped by parent
- **Stopped (T)**: Processes stopped by signal or debugger

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- PCP archives to process
- InfluxDB v2 instance
- Validated metrics configuration file

### Running the Parser

#### Windows (Recommended)

```cmd
cd C:\Users\yashvardhan.singh\PycharmProjects\pythonProject2\PCP\src
start-parsers.bat
```

#### Linux/Mac

```bash
cd /path/to/PCP/src
chmod +x start-parsers.sh
./start-parsers.sh
```

#### Manual (Docker Compose)

```bash
# Python parser only (default)
docker-compose --profile python-parser up -d

# Python + Go parsers
docker-compose --profile python-parser --profile go-parser up -d

# All three parsers
docker-compose --profile python-parser --profile go-parser --profile rust-parser up -d
```

### Environment Variables

Required environment variables (configured in `.env`):

```bash
# Parser Configuration - Set to 'true' to enable, 'false' to disable
ENABLE_PYTHON_PARSER=true   # Default: enabled
ENABLE_GO_PARSER=false      # Default: disabled
ENABLE_RUST_PARSER=false    # Default: disabled

# InfluxDB Configuration
INFLUXDB_URL=http://influxdb:8086
INFLUXDB_TOKEN=your-token-here
INFLUXDB_ORG=your-org
INFLUXDB_BUCKET=pcp-metrics

# Product Information
PRODUCT_TYPE=PCP
SERIAL_NUMBER=SN001

# Archive Configuration
ARCHIVE_DIR=/tmp/pcp_archives
VALIDATED_METRICS_FILE=/app/validated_metrics.txt

# Output Options
ENABLE_CSV_EXPORT=true
CSV_EXPORT_DIR=/tmp/csv_output
```

---

## Parser Configuration

All parser settings are controlled in the `.env` file. By default, **only the Python parser runs**.

### Configuration File: `.env`

```bash
# Parser Configuration - Set to 'true' to enable, 'false' to disable
ENABLE_PYTHON_PARSER=true   # Default: enabled
ENABLE_GO_PARSER=false      # Default: disabled
ENABLE_RUST_PARSER=false    # Default: disabled
```

### Common Configurations

#### 1. Default (Python Only)

**`.env` configuration:**
```bash
ENABLE_PYTHON_PARSER=true
ENABLE_GO_PARSER=false
ENABLE_RUST_PARSER=false
```

**Use case**: Production, stable, well-tested

**Command:**
```bash
start-parsers.bat
```

**Running containers:**
- `pcp_parser_python` ✓

---

#### 2. Python + Go (Performance Testing)

**`.env` configuration:**
```bash
ENABLE_PYTHON_PARSER=true
ENABLE_GO_PARSER=true
ENABLE_RUST_PARSER=false
```

**Use case**: Compare performance between Python and Go implementations

**Command:**
```bash
start-parsers.bat
```

**Running containers:**
- `pcp_parser_python` ✓
- `pcp_parser_go` ✓

**Note**: Both parsers will process the same archives in parallel

---

#### 3. All Parsers (Development/Testing)

**`.env` configuration:**
```bash
ENABLE_PYTHON_PARSER=true
ENABLE_GO_PARSER=true
ENABLE_RUST_PARSER=true
```

**Use case**: Development, benchmarking, feature comparison

**Command:**
```bash
start-parsers.bat
```

**Running containers:**
- `pcp_parser_python` ✓
- `pcp_parser_go` ✓
- `pcp_parser_rust` ✓

---

#### 4. Go Parser Only (High Performance)

**`.env` configuration:**
```bash
ENABLE_PYTHON_PARSER=false
ENABLE_GO_PARSER=true
ENABLE_RUST_PARSER=false
```

**Use case**: Production with Go parser (after testing)

**Command:**
```bash
start-parsers.bat
```

**Running containers:**
- `pcp_parser_go` ✓

---

### Stopping Parsers

#### Stop All

```bash
docker-compose down
```

#### Stop Specific Parser

```bash
# Stop Python parser
docker stop pcp_parser_python

# Stop Go parser
docker stop pcp_parser_go

# Stop Rust parser
docker stop pcp_parser_rust
```

---

### Viewing Logs

#### Python Parser

```bash
docker logs -f pcp_parser_python
```

#### Go Parser

```bash
docker logs -f pcp_parser_go
```

#### Rust Parser

```bash
docker logs -f pcp_parser_rust
```

#### All Parsers

```bash
# Windows PowerShell
Get-ChildItem -Filter "pcp_parser_*" | ForEach-Object { docker logs --tail 50 $_.Name }

# Linux/Mac
docker ps --filter "name=pcp_parser" --format "{{.Names}}" | xargs -I {} docker logs --tail 50 {}
```

---

### Rebuilding Parsers

#### Rebuild Specific Parser

```bash
# Python
docker-compose build pcp_parser_python

# Go
docker-compose build pcp_parser_go

# Rust
docker-compose build pcp_parser_rust
```

#### Rebuild with No Cache

```bash
docker-compose build --no-cache pcp_parser_python
```

---

### Parser Architecture

#### How Profiles Work

Docker Compose profiles allow selective service startup:

```yaml
# docker-compose.yml
services:
  pcp_parser_python:
    profiles:
      - python-parser    # Only starts with --profile python-parser
    ...

  pcp_parser_go:
    profiles:
      - go-parser        # Only starts with --profile go-parser
    ...
```

When you run `docker-compose up -d` without profiles, **no parsers start**.

When you run `docker-compose --profile python-parser up -d`, **only Python parser starts**.

The `start-parsers.bat` script reads `.env` and automatically adds the correct profiles.

---

#### Log Directory Structure

Each parser has its own log directory:

```
/src/logs/
├── pcp_parser_python/
│   ├── pcp_parser.log
│   └── pmrep_output_*.csv (if CSV enabled)
├── pcp_parser_go/
│   ├── pcp_parser.log
│   └── pmrep_output_*.csv (if CSV enabled)
└── pcp_parser_rust/
    ├── pcp_parser.log
    └── pmrep_output_*.csv (if CSV enabled)
```

---

#### Archive Processing - Parallel Processing

When multiple parsers are enabled, they process archives **in parallel**:

1. Archive arrives in `/src/input/raw/`
2. All enabled parsers detect it simultaneously
3. Each parser:
   - Extracts archive to its own temp directory
   - Processes metrics
   - Exports to InfluxDB
4. First parser to complete moves archive to `/src/archive/processed/`
5. Other parsers skip the moved archive

**Coordination**:

Parsers coordinate using:
- **File locks**: Prevent simultaneous processing
- **Parser ID**: Each parser has unique identifier (`PARSER_ID` env var)
- **Processed directory**: Shared success indicator

---

### Best Practices

1. **Production**: Use Python parser only (`ENABLE_PYTHON_PARSER=true`, others `false`)
2. **Development**: Enable all parsers for testing
3. **Performance Testing**: Enable Python + one other for comparison
4. **Always check logs** after starting: `docker logs -f pcp_parser_python`
5. **Rebuild after code changes**: `docker-compose build pcp_parser_python`
6. **Use `start-parsers.bat`** instead of manual docker-compose commands

---

## Configuration

### Process State Filtering

Configure which process states to capture by editing `pcp_parser.py`:

**Location**: `pcp_parser.py`, function `parse_proc_psinfo_sname_from_process()`, lines 433-442

```python
# ============================================================
# CONFIGURATION: Process states to CAPTURE (include in export)
# ============================================================
# Empty set = capture ALL states (default)
# To filter specific states, specify them here:
# Examples:
#   set()             - Capture ALL states (R, D, S, I, Z, T) - DEFAULT
#   {'R', 'D'}        - Capture only Running and Blocked
#   {'R', 'D', 'Z'}   - Capture Running, Blocked, and Zombie
CAPTURE_PROCESS_STATES = set()  # Default: Capture ALL
# ============================================================
```

#### Common Configurations

**1. All States (Default)**
```python
CAPTURE_PROCESS_STATES = set()
```
- Captures: R, D, S, I, Z, T
- Use case: Complete system monitoring
- Data volume: Very high (200-500+ processes)

**2. Critical States Only**
```python
CAPTURE_PROCESS_STATES = {'R', 'D'}
```
- Captures: Running and Blocked only
- Use case: Monitor active resource usage
- Data volume: Very low (5-20 processes)

**3. Production Monitoring**
```python
CAPTURE_PROCESS_STATES = {'R', 'D', 'Z', 'T'}
```
- Captures: Running, Blocked, Zombie, Stopped
- Use case: Balance between detail and cost
- Data volume: Low-Medium (10-50 processes)

---

## Process Metrics

### Enabling Process Metrics Collection

The `proc.psinfo.sname` metric is **not collected by default** in PCP archives due to high cardinality and storage overhead.

#### Why Process Metrics May Be Missing

When you see this message:
```
proc.psinfo.sname metric not found in this archive - skipping
This metric requires process metrics to be enabled during collection
```

This happens because:
- **High cardinality**: Each running process creates a separate instance
- **Storage overhead**: Process metrics can generate large amounts of data
- **Performance impact**: Collecting all process details can impact system performance

### Enabling Process Metrics During Collection

#### Method 1: Create Custom pmlogger Configuration

Create a configuration file `/etc/pcp/pmlogger/config.default`:

```bash
# Process state metrics - only state changes
log mandatory on 1 sec {
    proc.psinfo.sname
    proc.nprocs
    proc.runq.runnable
    proc.runq.blocked
}

# Optional: Add other process metrics
log mandatory on 5 sec {
    proc.memory.rss
    proc.memory.size
    proc.psinfo.maj_flt
}
```

#### Method 2: Create Test Archives with Process Metrics

```bash
# Create a custom config file
cat > /tmp/proc-metrics.conf << EOF
log mandatory on 1 sec {
    proc.psinfo.sname
    proc.nprocs
    proc.runq.runnable
    proc.runq.blocked
    kernel.all.cpu.user
    kernel.all.cpu.sys
    mem.util.used
}
EOF

# Run pmlogger with this config for 60 seconds
pmlogger -c /tmp/proc-metrics.conf -t 1sec -s 60 /tmp/test-with-proc

# Compress the archive
cd /tmp
tar -cJf test-with-proc.tar.xz test-with-proc.*

# Copy to pcp_parser folder for testing
cp test-with-proc.tar.xz /path/to/pcp_parser/
```

#### Method 3: Verify Process Metrics in Archive

```bash
# List all metrics in the archive
pminfo -a /path/to/archive | grep proc.psinfo

# Check specific metric
pminfo -a /path/to/archive proc.psinfo.sname

# View sample data
pmval -a /path/to/archive -s 3 proc.psinfo.sname
```

### Performance Considerations

**Warning**: Enabling process metrics can significantly increase:
- Archive file size (10x-100x larger)
- CPU overhead during collection
- Memory usage
- Disk I/O

**Recommendations**:
1. **Sample less frequently**: Use 5-10 second intervals instead of 1 second
2. **Limit metrics**: Only collect essential process metrics
3. **Use filtering**: Configure pmlogger to only log specific processes if possible
4. **Monitor disk space**: Process metrics archives grow very quickly

---

## Performance Optimization

### Parallel Processing

The parser uses parallel processing to reduce total processing time by 30-50%.

#### How It Works

**Before (Sequential)**:
```
1. Run pmrep to export all standard metrics   → Takes X seconds
2. Wait for pmrep to complete
3. Run pmrep to export proc.psinfo.sname      → Takes Y seconds
4. Wait for pmrep to complete

Total time: X + Y seconds
```

**After (Parallel)**:
```
1. Check if proc.psinfo.sname exists          → Takes ~1 second
2. Start pmrep in background (if available)   → Non-blocking
3. Start pmrep to export standard metrics     → Takes X seconds
4. Process pmrep output
5. Wait for pmrep to complete (if running)    → Usually already done!
6. Process pmrep output

Total time: ~X seconds (Y happens in parallel)
```

#### Example Timings

For a typical PCP archive:

| Phase | Sequential | Parallel |
|-------|-----------|----------|
| pmrep export (standard) | 60 sec | 60 sec |
| pmrep export (process) | 45 sec | ~0 sec (parallel) |
| **Total** | **105 sec** | **~60 sec** |

**Time saved: ~45 seconds (43% faster)**

### Resource Usage

#### CPU
- **Sequential**: Single-core usage
- **Parallel**: Multi-core usage
- **Impact**: Better CPU utilization, no increase in peak usage

#### Memory
- **Sequential**: One process at a time
- **Parallel**: Two processes simultaneously
- **Impact**: Slightly higher memory usage (~2x for pmrep output buffer)
- **Typical**: +50-100 MB during processing

#### I/O
- **Sequential**: Archive read twice
- **Parallel**: Archive read twice (may benefit from filesystem cache)

---

## InfluxDB Schema

### Standard Metrics

All standard metrics use the following schema:

**Tags** (indexed):
- `product_type`: Product type identifier (e.g., "PCP")
- `serialNumber`: Serial number of the system

**Fields**: Metric-specific values

**Timestamp**: Nanosecond precision Unix timestamp

### Process State Metrics

#### Measurement: `proc_psinfo_sname`

**Tags** (indexed - use for filtering):
- `product_type`: Product type identifier (e.g., "PCP")
- `serialNumber`: Serial number
- `process_name`: Full process path (e.g., "/usr/bin/python3")
- `pid`: Process ID with leading zeros (e.g., "012345")
- `state`: Single-letter state code (R, D, S, I, Z, T)

**Fields** (values - not indexed):
- `state_description`: Human-readable state name (e.g., "Running", "Blocked")

#### Example Data Points

**Running Process**:
```
proc_psinfo_sname,product_type=PCP,serialNumber=SN001,process_name=/usr/bin/python3,pid=012345,state=R state_description="Running" 1699876543000000000
```

**Blocked Process**:
```
proc_psinfo_sname,product_type=PCP,serialNumber=SN001,process_name=/usr/sbin/dmeventd,pid=000720,state=D state_description="Blocked" 1699876544000000000
```

**Zombie Process**:
```
proc_psinfo_sname,product_type=PCP,serialNumber=SN001,process_name=/opt/app/worker,pid=098765,state=Z state_description="Zombie" 1699876545000000000
```

### Querying InfluxDB

#### Query All Running Processes

```flux
from(bucket: "pcp-metrics")
  |> range(start: -1h)
  |> filter(fn: (r) => r["_measurement"] == "proc_psinfo_sname")
  |> filter(fn: (r) => r["state"] == "R")
  |> last()
```

#### Query All Blocked Processes

```flux
from(bucket: "pcp-metrics")
  |> range(start: -1h)
  |> filter(fn: (r) => r["_measurement"] == "proc_psinfo_sname")
  |> filter(fn: (r) => r["state"] == "D")
  |> last()
```

#### Query Specific Process by Name

```flux
from(bucket: "pcp-metrics")
  |> range(start: -1h)
  |> filter(fn: (r) => r["_measurement"] == "proc_psinfo_sname")
  |> filter(fn: (r) => r["process_name"] =~ /python/)
  |> last()
```

#### Count Processes by State

```flux
from(bucket: "pcp-metrics")
  |> range(start: -1h)
  |> filter(fn: (r) => r["_measurement"] == "proc_psinfo_sname")
  |> group(columns: ["state"])
  |> count()
```

#### Find Zombie Processes

```flux
from(bucket: "pcp-metrics")
  |> range(start: -1h)
  |> filter(fn: (r) => r["_measurement"] == "proc_psinfo_sname")
  |> filter(fn: (r) => r["state"] == "Z")
  |> last()
```

#### Alert: Too Many Blocked Processes

Condition: More than 20 processes in D state

```flux
from(bucket: "pcp-metrics")
  |> range(start: -5m)
  |> filter(fn: (r) => r["_measurement"] == "proc_psinfo_sname")
  |> filter(fn: (r) => r["state"] == "D")
  |> count()
  |> map(fn: (r) => ({
      _time: r._time,
      _value: r._value,
      _level: if r._value > 20 then "crit" else "ok"
    }))
```

---

## Logging

The parser provides comprehensive logging at multiple levels:

### Log Levels

- **INFO**: Normal operation messages, statistics, and progress
- **DEBUG**: Detailed processing information (individual lines, timestamps, points)
- **WARNING**: Non-critical issues (no data found, errors during creation)
- **ERROR**: Critical failures (metric not found, parsing errors, InfluxDB write failures)

### Key Log Sections

#### 1. Metric Discovery
```
============================================================
PROCESSING proc.psinfo.sname METRIC
============================================================
Parsing proc.psinfo.sname for Running (R) and Blocked (D) processes...
Archive: /path/to/archive
```

#### 2. Metric Availability Check

**When found**:
```
✓ proc.psinfo.sname metric found in archive
```

**When NOT found**:
```
⚠️  proc.psinfo.sname metric NOT found in this archive - skipping
    This metric requires process metrics to be enabled during collection
```

#### 3. Parsing Statistics
```
============================================================
PARSING COMPLETE - Statistics:
  Total lines processed: 15234
  Running (R) processes: 45
  Blocked (D) processes: 12
  Total R+D data points: 57
  Skipped states (total: 15177):
    - Idle (I): 8234
    - Sleeping (S): 6943
============================================================
```

#### 4. Sample Data
```
Sample Running/Blocked processes:
  17:30:45.123 - PID 077644 (/var/lib/pcp/pmdas/proc/pmdaproc): Running
  17:30:45.123 - PID 077648 (/var/lib/pcp/pmdas/linux/pmdalinux): Blocked
  17:30:46.124 - PID 125048 (snmpbulkget): Running
  ... and 54 more
```

#### 5. Export Results

**Success**:
```
Writing 57 points to InfluxDB...
✓ Successfully wrote 57 proc.psinfo.sname points to InfluxDB
  Running (R): 45 points
  Blocked (D): 12 points
============================================================
```

**No data**:
```
No process state data to export - skipping
```

**Failure**:
```
✗ Failed to write points to InfluxDB: {error message}
```

### Enabling Debug Logs

To see detailed debug logs, ensure the logging level is set to DEBUG:

```python
logger.setLevel(logging.DEBUG)
```

Debug logs will show:
- Individual timestamps being processed
- Each process state line being added or skipped
- Individual InfluxDB points being created
- pmrep command details

---

## Sample Archives

### Included Sample Archive

**`pcp_sample_archive.tar.xz`**
- **Source**: Copied from `sampleData/20250915.tar.xz`
- **Size**: 2.3 MB
- **Purpose**: Sample PCP archive for testing the parser

### About pcp_data_sample.log.txt

The `pcp_data_sample.log.txt` file is a **text dump** created by running `pmdumplog` on a PCP archive. It contains:
- Log metadata (host, timestamps, timezone)
- Metric descriptions (PMID, data types, semantics)
- Time-series data in human-readable format

**Important**: It is NOT possible to reverse engineer `pcp_data_sample.log.txt` back into a binary PCP archive because:
1. **Binary Format Loss**: PCP archives use a proprietary binary format (`.meta`, `.index`, `.0` files)
2. **Information Loss**: The text dump doesn't preserve binary precision, encoding, and internal structures
3. **PCP Tools Required**: To create real PCP archives, you must use official PCP tools (`pmlogger`, `pmlogextract`, `pmlogrewrite`)

### Using the Sample Archive

```bash
# Extract the archive
tar -xJf pcp_sample_archive.tar.xz

# View archive contents with PCP tools
pmdumplog -a <archive_base>
pminfo -a <archive_base>
pmrep -a <archive_base> -t 1sec -o csv <metrics>
```

### Creating Test Archives

If you need to create test PCP archives with specific data:

**1. Use pmlogger on a live system**:
```bash
pmlogger -t 1sec -s 60 myarchive
```

**2. Use configuration files to define metrics**:
```bash
pmlogger -c myconfig.conf -t 1sec myarchive
```

**3. Compress the result**:
```bash
tar -cJf myarchive.tar.xz myarchive.*
```

---

## Troubleshooting

### Parser Configuration Issues

#### Error: "No parsers enabled!"

**Problem**: All parser flags are set to `false` in `.env`

**Solution**: Enable at least one parser:
```bash
ENABLE_PYTHON_PARSER=true
```

#### Error: "Container already exists"

**Problem**: Container from previous run still exists

**Solution**:
```bash
docker-compose down
start-parsers.bat
```

#### Parser Not Starting

**Problem**: Profile not specified or incorrect

**Check running containers**:
```bash
docker ps --filter "name=pcp_parser"
```

**Manual start with profile**:
```bash
docker-compose --profile python-parser up -d
```

#### Code Changes Not Reflected

**Problem**: Docker using cached image

**Solution**: Rebuild with no cache
```bash
docker-compose down
docker-compose build --no-cache pcp_parser_python
start-parsers.bat
```

---

### Process Metrics Not Found

**Symptom**:
```
⚠️  proc.psinfo.sname metric NOT found in this archive - skipping
```

**Cause**: Archive doesn't contain process metrics (not enabled during collection)

**Solution**: Enable process metrics during PCP collection (see [Enabling Process Metrics](#enabling-process-metrics-during-collection))

### No Data Captured

**Symptom**:
```
⚠️  No process state data captured (all states may be filtered)
```

**Cause**: All states are being filtered by `CAPTURE_PROCESS_STATES` configuration

**Solution**: Check `CAPTURE_PROCESS_STATES` configuration in `pcp_parser.py`

### Too Much Data

**Symptom**: InfluxDB writes taking a long time, large database size

**Cause**: `CAPTURE_PROCESS_STATES = set()` (capturing all states including S, I)

**Solution**: Limit to critical states:
```python
CAPTURE_PROCESS_STATES = {'R', 'D', 'Z', 'T'}
```

### Missing Zombie Processes

**Symptom**: Known zombie processes not appearing in Grafana

**Cause**: Zombies are being filtered out

**Solution**: Ensure 'Z' is included in `CAPTURE_PROCESS_STATES`:
```python
CAPTURE_PROCESS_STATES = {'R', 'D', 'Z'}  # Include Z
```

### pmrep Process Hanging

**Symptom**:
```
⚠️  pmrep process timed out after 120 seconds
```

**Solutions**:
1. Increase timeout in `parse_proc_psinfo_sname_from_process()`
2. Check if archive is corrupted
3. Verify sufficient memory available

### InfluxDB Write Failures

**Symptom**:
```
✗ Failed to write points to InfluxDB: {error}
```

**Check**:
- InfluxDB connectivity
- Bucket name configuration
- Token permissions
- Schema conflicts (measurement already exists with different schema)

### Memory Issues

**Symptom**: Out of memory errors during processing

**Solutions**:
1. Reduce pmrep timeout (processes smaller chunks)
2. Increase container memory limits
3. Process archives with fewer process instances
4. Enable filtering to reduce data volume

---

## Performance Monitoring

### Check Processing Time

Look for these log entries to measure performance:

```
===== STARTING EXPORT TO INFLUXDB =====
✓ proc.psinfo.sname metric available - will process in parallel
...
===== EXPORT COMPLETE =====
Total data points written: 45230
proc.psinfo.sname: 57 Running/Blocked process states exported
```

The time between "STARTING EXPORT" and "proc.psinfo.sname exported" is your total processing time.

### Expected Timeline

For a 1-hour archive:

| Event | Time | Notes |
|-------|------|-------|
| Start export | 0:00 | Both processes start |
| pmrep completes (process) | ~0:45 | Usually finishes first |
| pmrep completes (standard) | ~1:00 | Main export done |
| Collect pmrep results | ~1:00 | Already finished! |
| **Total** | **~1:00** | Instead of 1:45 |

---

## Data Volume Comparison

For a typical 1-hour archive:

| Filter Configuration | Processes Captured | Data Points | InfluxDB Size |
|---------------------|-------------------|-------------|---------------|
| `{'R', 'D'}` (critical only) | ~10-20 | ~600-1,200 | ~50 KB |
| `{'R', 'D', 'Z', 'T'}` (recommended) | ~20-50 | ~1,200-3,000 | ~150 KB |
| `set()` (ALL states) | ~200-500 | ~12,000-30,000 | ~2 MB |

---

## Recent Changes

### Process State Parsing Improvements

**Changed from pmval to pmrep**:
- **Before**: Used `pmval` which outputs complex text format
- **After**: Use `pmrep -o csv` which outputs simple CSV format
- **Why**: CSV format is much simpler to parse and more reliable

**Changed SKIP to CAPTURE Logic**:
- **Before**: `SKIP_PROCESS_STATES = {'S', 'I'}` (skip these states)
- **After**: `CAPTURE_PROCESS_STATES = set()` (capture only these states, empty = ALL)
- **Why**: More intuitive - specify what you WANT, not what you DON'T want

**Default Behavior**:
- **Before**: By default skipped S and I states
- **After**: By default captures ALL states (R, D, S, I, Z, T)
- **Why**: More flexible and comprehensive by default

---

## Quick Reference

### Start Only Python Parser (Default)

```bash
# Edit .env
ENABLE_PYTHON_PARSER=true
ENABLE_GO_PARSER=false
ENABLE_RUST_PARSER=false

# Start
start-parsers.bat
```

### Start Python + Go Parsers

```bash
# Edit .env
ENABLE_PYTHON_PARSER=true
ENABLE_GO_PARSER=true
ENABLE_RUST_PARSER=false

# Start
start-parsers.bat
```

### Check What's Running

```bash
docker ps --filter "name=pcp_parser"
```

### View Logs

```bash
docker logs -f pcp_parser_python
```

### Stop Everything

```bash
docker-compose down
```

### Rebuild and Restart

```bash
docker-compose down
docker-compose build pcp_parser_python
start-parsers.bat
```

---

## Usage Examples

### Example 1: Fresh Start with Python Parser

```bash
cd C:\Users\yashvardhan.singh\PycharmProjects\pythonProject2\PCP\src

# Ensure .env has Python enabled
echo ENABLE_PYTHON_PARSER=true > .env.tmp
echo ENABLE_GO_PARSER=false >> .env.tmp
echo ENABLE_RUST_PARSER=false >> .env.tmp

# Stop any running containers
docker-compose down

# Start with configuration
start-parsers.bat

# Verify
docker ps --filter "name=pcp_parser"
```

### Example 2: Switch from Python to Go

```bash
# Stop current parser
docker-compose down

# Edit .env
ENABLE_PYTHON_PARSER=false
ENABLE_GO_PARSER=true

# Start new parser
start-parsers.bat
```

### Example 3: Run All Parsers for Benchmark

```bash
# Edit .env
ENABLE_PYTHON_PARSER=true
ENABLE_GO_PARSER=true
ENABLE_RUST_PARSER=true

# Start all
start-parsers.bat

# Monitor all logs
docker-compose logs -f pcp_parser_python pcp_parser_go pcp_parser_rust
```

---

## Contributing

When modifying the parser:

1. **Test with real archives**: Always test with actual PCP archives that contain process metrics
2. **Check logs**: Review all log output to ensure proper parsing and export
3. **Verify InfluxDB**: Check that data appears correctly in InfluxDB with proper schema
4. **Monitor performance**: Measure processing time before and after changes
5. **Update documentation**: Keep this README in sync with code changes

---

## Support

For issues or questions:
1. Check the [Troubleshooting](#troubleshooting) section
2. Review log output for specific error messages
3. Verify configuration settings
4. Test with sample archives to isolate issues

---

## License

[Add your license information here]
