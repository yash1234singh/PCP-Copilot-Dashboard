# PCP Parser (Python Implementation)

Python-based parser for Performance Co-Pilot (PCP) archives that exports metrics to InfluxDB.

> **📖 Main Documentation**: See [../README.md](../README.md) for complete system architecture, configuration, and usage.

---

## Overview

This is the **Python implementation** of the PCP parser. It's the default parser with comprehensive feature support.

**Processing Modes** (automatic selection):
- **Pandas Mode**: Vectorized processing - used when pandas is installed
- **Streaming Mode**: Line-by-line processing (low memory) - automatic fallback


---

## Quick Start

### Using Web Interface (Recommended)

1. Access web UI: http://localhost:5000
2. Upload `.tar.xz` archive
3. Click "Process All Files (Python)"

### Using Docker Compose

```bash
# Start the Python parser
cd /path/to/PCP/src
docker-compose up -d pcp_parser_python

# View logs
docker logs -f pcp_parser_python

# Stop
docker stop pcp_parser_python
```

---

## Configuration

### Essential Flags (docker-compose.yml)

```yaml
# Output control
SAVE_CSV_OUTPUT=true              # Save CSV for debugging
ENABLE_INFLUXDB_WRITE=true        # Enable InfluxDB writes

# Performance tuning
INFLUX_BATCH_SIZE=50000           # Batch size for writes
VALIDATION_BATCH_SIZE=500         # Batch size for validation
PROGRESS_LOG_INTERVAL=50          # Log every N batches
```

### Metric Category Filters

Control which metric categories to process:

```yaml
ENABLE_PROCESS_METRICS=false      # proc.* (high cardinality)
ENABLE_DISK_METRICS=true          # disk.*
ENABLE_FILE_METRICS=false         # vfs.*, filesys.*
ENABLE_MEMORY_METRICS=true        # mem.*
ENABLE_NETWORK_METRICS=true       # network.*
ENABLE_KERNEL_METRICS=true        # kernel.*
ENABLE_SWAP_METRICS=false         # swap.*
ENABLE_NFS_METRICS=false          # nfs.* (often errors)
```

### Value Filters

```yaml
PCP_METRICS_FILTER=skip_empty,skip_none  # Comma-separated
# Options: skip_zero, skip_empty, skip_none
```

### Validation Control

```yaml
SKIP_VALIDATION=false             # Skip validation (risky!)
FORCE_REVALIDATE=false            # Re-validate cached metrics
```

---

## Processing Modes

The parser **automatically selects** the processing mode:

### Pandas Mode (Default)

**When**: Pandas is installed (default in Docker)

**How it works**:
1. Collect CSV output in memory buffer
2. Parse with `pd.read_csv()` (vectorized)
3. Convert to InfluxDB line protocol
4. Batch write to InfluxDB

**Characteristics**: Vectorized processing with memory buffer

### Streaming Mode (Fallback)

**When**: Pandas not available

**How it works**:
1. Read pmrep stdout line-by-line
2. Parse each line immediately
3. Create InfluxDB points
4. Batch write to InfluxDB

**Performance**: Lower memory footprint

---

## Process State Monitoring

### Enabling proc.psinfo.sname

By default, `proc.psinfo.sname` processing is **disabled** to avoid timeouts:

```yaml
ENABLE_SNAME_PROCESSING=false     # Change to 'true' to enable
```

### Configuring Process State Filtering

Edit `pcp_parser.py` around line 561:

```python
# Capture specific states only (R=Running, D=Blocked, I=Idle)
CAPTURE_PROCESS_STATES = {
    'R',  # Running
    'D',  # Blocked (I/O wait)
    'I',  # Idle
}

# Or capture ALL states (R, D, S, I, Z, T)
CAPTURE_PROCESS_STATES = set()  # Empty set = ALL states
```

**State Descriptions**:
- **R**: Running (actively using CPU)
- **D**: Blocked (waiting for I/O - potential bottleneck)
- **S**: Sleeping (idle, waiting for events)
- **I**: Idle (kernel threads)
- **Z**: Zombie (terminated, not reaped)
- **T**: Stopped (by signal/debugger)

---

## Key Functions

| Function | Purpose | Lines |
|----------|---------|-------|
| `process_archive()` | Main processing loop | ~100 |
| `get_available_metrics()` | Metric discovery & validation | ~130 |
| `validate_metrics_parallel()` | Parallel metric validation | ~20 |
| `export_to_influxdb()` | Data transformation & export | ~500 |
| `parse_proc_psinfo_sname_from_process()` | Process state parsing | ~250 |
| `export_proc_sname_to_influxdb()` | Process state export | ~100 |

---

## Dockerfile

### Base Image
```dockerfile
FROM ubuntu:22.04
```

### Installed Packages
- **PCP**: pminfo, pmrep, pmval
- **Python 3**: Runtime
- **pip packages**: influxdb-client, requests, pandas, numpy

### Configuration
```dockerfile
ENV SAVE_CSV_OUTPUT=false
ENV INFLUX_BATCH_SIZE=200000
```

---

## Logging

Logs are written to: `/src/logs/pcp_parser_python/pcp_parser.log`

### Log Levels
- **INFO**: Progress, statistics, milestones
- **DEBUG**: Detailed processing info
- **WARNING**: Non-critical issues
- **ERROR**: Critical failures

### Key Log Sections

```
[FLOW] === PROCESSING MODE CONFIGURATION ===
[FLOW] DATA READING MODE: PANDAS (vectorized)

[FLOW] === PHASE 1: ARCHIVE EXTRACTION ===
[FLOW] ✓ Extracted in 2.34s

[FLOW] === PHASE 2: METRIC VALIDATION ===
Parallel validation: 2000 metrics with 100 workers
✓ Found 1850 valid metrics

[FLOW] === PHASE 3: DATA EXPORT ===
[FLOW] === STEP 4: PANDAS MODE (MEMORY BUFFER) ===
[FLOW] ✓ Collected 50000 lines in memory
[FLOW] === STEP 6: INFLUXDB ASYNC WRITES ===
✓ Pandas+LineProtocol: 245000 points written

✓ Successfully exported archive to InfluxDB
⏱️  TOTAL PROCESSING TIME: 2 minutes 15.45 seconds
```

---

## Troubleshooting

### No Data in InfluxDB

**Check**:
1. `ENABLE_INFLUXDB_WRITE=true` in docker-compose.yml
2. InfluxDB is running: `docker ps | grep influxdb`
3. Token/bucket configured correctly
4. Check logs for write errors

### Processing Too Slow

**Solutions**:
1. Ensure pandas is installed (check logs for "PANDAS" mode)
2. Increase `INFLUX_BATCH_SIZE` to 100000+
3. Use validated_metrics.txt to skip validation
4. Reduce metric categories (disable proc.*, file.*)

### Out of Memory

**Solutions**:
1. Disable `SAVE_CSV_OUTPUT` to save memory
2. Reduce metric count (use category filters)
3. Increase Docker memory limits
4. Process smaller archives

### Validation Taking Too Long

**Solutions**:
1. Create `input/data_filter/validated_metrics.txt` with pre-validated metrics
2. Set `SKIP_VALIDATION=true` (risky - may cause errors)
3. Use batch validation (already automatic with 100 workers)

---

## Performance Benchmarks

### Typical 1-Hour Archive (2000 metrics, 3600 samples)

| Metric | Value |
|--------|-------|
| **Archive Size** | 50 MB (compressed) |
| **Extraction Time** | 3-5 seconds |
| **Validation Time** | 15-30 seconds (first run), <1s (cached) |
| **Export Time** | 60-90 seconds (pandas), 120-150s (streaming) |
| **Total Points** | ~200,000-500,000 |
| **InfluxDB Size** | 5-15 MB |

### Mode Comparison

| Mode | Time | Memory | CPU |
|------|------|--------|-----|
| **Pandas** | 60s | 500MB | 80% |
| **Streaming** | 120s | 100MB | 40% |

---

## Development

### File Structure
```
pcp_parser/
├── Dockerfile                # Container build
├── pcp_parser.py            # Main parser (1750 lines)
├── s3_parquet_exporter.py   # S3 Parquet export module
└── README.md                # This file
```

### Making Changes

1. Edit `pcp_parser.py`
2. Rebuild container:
   ```bash
   docker-compose build pcp_parser_python
   ```
3. Restart:
   ```bash
   docker-compose up -d pcp_parser_python
   ```
4. Test with sample archive
5. Check logs for errors

### Code Style

- Function-oriented design
- Clear, descriptive names
- Type hints where applicable
- Comprehensive logging
- Error handling with try/except

---

## AWS S3 Parquet Export

Export PCP metrics to AWS S3 in Parquet format with automatic partitioning for efficient querying.

### Features

✅ Automatic partitioning by date (year/month/day/hour), product_type, serial_number
✅ Columnar Parquet format (5-10x smaller than CSV)
✅ Multiple compression options (snappy, gzip, brotli, lz4, zstd)
✅ AWS Athena compatible (query with SQL)
✅ Optional - doesn't affect InfluxDB export

### Quick Start

**1. Configure S3 settings in `docker-compose.yml`:**

Edit the S3 configuration section (lines 125-133):

```yaml
# S3 Parquet export configuration
- ENABLE_S3_EXPORT=true                     # Change to 'true' to enable
- S3_BUCKET_NAME=fst-pcp-data1              # Your bucket name (NOT ARN)
- S3_KEY_PREFIX=                            # Optional: directory prefix (e.g., "metrics/prod/")
- AWS_REGION=us-west-2                      # Region where your bucket is located
- PARQUET_COMPRESSION=snappy                # Compression algorithm
- PARQUET_ROW_GROUP_SIZE=100000             # Rows per row group
```

**Bucket name explanation:**
- ✅ Correct: `fst-pcp-data1` (bucket name only)
- ❌ Wrong: `arn:aws:s3:::fst-pcp-data1` (ARN format not supported)

**S3_KEY_PREFIX explanation:**
- Acts as a folder path prefix before auto-generated partitions
- Empty (`""`) = bucket root → `s3://bucket/year=2025/month=11/...`
- `"metrics/prod/"` → `s3://bucket/metrics/prod/year=2025/month=11/...`

**AWS_REGION explanation:**
- MUST match the region where your S3 bucket was created
- Why needed: S3 API endpoints are region-specific
- Common regions: `us-east-1`, `us-west-2`, `eu-west-1`, `ap-southeast-1`

**2. Add AWS credentials to `.env` file:**

```bash
# Uncomment and add your AWS credentials
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
```

**3. Rebuild and restart:**

```bash
docker-compose build pcp_parser_python
docker-compose up -d pcp_parser_python
```

**4. Test S3 Write Functionality:**

Before processing real data, verify S3 write permissions with the test script:

```bash
# Method 1: Run test script directly in container
docker exec pcp_parser_python python3 test_s3_write.py

# Method 2: Run bash wrapper (from src/ directory)
cd src/
./test_s3.sh

# Method 3: Use docker-compose exec
docker-compose exec pcp_parser_python python3 test_s3_write.py
```

**Expected Output**: All 5 tests should pass:
```
✓ Test 1: AWS Credentials Check - PASSED
✓ Test 2: S3 Connection Test - PASSED
✓ Test 3: Simple File Upload - PASSED
✓ Test 4: Parquet File Upload - PASSED
✓ Test 5: List Files Verification - PASSED

🎉 ALL TESTS PASSED! AWS S3 write is fully functional.
```

### S3 Write Test Details

The `test_s3_write.py` script provides comprehensive testing:

#### Test 1: AWS Credentials Check
- **Purpose**: Verify AWS credentials are configured
- **Checks**: `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` are set
- **Common Failure**:
  ```
  ✗ FAILED: AWS credentials not found in environment
  ```
  **Fix**: Add credentials to `.env` file

#### Test 2: S3 Connection Test
- **Purpose**: Verify connection to S3 and bucket access
- **Checks**: S3 client creation, bucket exists, region is correct
- **Common Failures**:
  - `Bucket does not exist` - Create bucket or update `S3_BUCKET_NAME`
  - `Access denied` - Add IAM permission `s3:ListBucket`

#### Test 3: Simple File Upload
- **Purpose**: Test basic S3 write permission
- **Checks**: Can upload simple text file (`s3:PutObject` permission)
- **Common Failure**:
  ```
  ✗ FAILED: Access denied
    Missing IAM permission: s3:PutObject
  ```
  **Fix**: Add IAM policy:
  ```json
  {
    "Effect": "Allow",
    "Action": "s3:PutObject",
    "Resource": "arn:aws:s3:::fst-pcp-data1/*"
  }
  ```

#### Test 4: Parquet File Upload
- **Purpose**: Test complete Parquet export workflow
- **Checks**: DataFrame creation, Parquet conversion, Hive-style partitioning, S3 upload
- **Creates**: Test Parquet file at path like:
  ```
  s3://fst-pcp-data1/test/year=2025/month=11/day=19/hour=01/
    product_type=SW_DEV_11/serial_number=1235678/test_20251119_014640.parquet
  ```

#### Test 5: List Files Verification
- **Purpose**: Verify uploaded files can be listed
- **Checks**: Can list bucket contents, test files are visible
- **Common Failure**: `Access denied` - Add IAM permission `s3:ListBucket`

### Required IAM Permissions

Minimum required permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PCPParquetExportPermissions",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::fst-pcp-data1",
        "arn:aws:s3:::fst-pcp-data1/*"
      ]
    }
  ]
}
```

| Permission | Purpose | Required For |
|------------|---------|--------------|
| `s3:PutObject` | Upload files | Tests 3, 4 |
| `s3:ListBucket` | List files | Tests 2, 5 |
| `s3:GetObject` | Read files (optional) | Future use |

### Test Files Created

All test files are created under the `test/` prefix:

```
s3://fst-pcp-data1/
└── test/
    ├── test.txt                              # Simple text file
    ├── test_YYYYMMDD_HHMMSS.txt             # Timestamped text file
    └── year=2025/month=11/day=19/hour=01/
        └── product_type=SW_DEV_11/
            └── serial_number=1235678/
                └── test_YYYYMMDD_HHMMSS.parquet
```

**Cleanup Test Files**:
```bash
# AWS CLI
aws s3 rm s3://fst-pcp-data1/test/ --recursive

# AWS Console: Navigate to bucket → test/ folder → Delete
```

### Troubleshooting

| Issue | Solution |
|-------|----------|
| Container not running | `docker-compose up -d pcp_parser_python` |
| Import errors | `docker-compose build pcp_parser_python` |
| Credentials not found | Check `.env` file has `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` |
| Wrong region | Ensure `AWS_REGION` matches bucket's region: `aws s3api get-bucket-location --bucket fst-pcp-data1` |

### S3 Bucket Structure

```
s3://your-bucket/time-series-data/
└── year=2025/month=11/day=13/hour=14/product_type=SERVER1/serial_number=1234/
    └── data_20251113_143045.parquet
```

### Querying with AWS Athena

```sql
CREATE EXTERNAL TABLE pcp_metrics (
    timestamp TIMESTAMP,
    kernel_all_cpu_idle DOUBLE,
    mem_util_used DOUBLE
)
PARTITIONED BY (year, month, day, hour, product_type, serial_number)
STORED AS PARQUET
LOCATION 's3://your-bucket/time-series-data/';

MSCK REPAIR TABLE pcp_metrics;

SELECT * FROM pcp_metrics
WHERE year='2025' AND month='11' AND day='13'
  AND product_type='SERVER1' LIMIT 100;
```

### Performance

- **Compression**: 50 MB CSV → 5-10 MB Parquet
- **Upload**: 2-5 seconds per archive
- **Cost**: ~$0.20/month per server (24 archives/day, 30 days)

### Testing

```bash
# Test S3 connection
docker exec -it pcp_parser_python python3 -c "
from s3_parquet_exporter import test_s3_connection
import logging; logging.basicConfig(level=logging.INFO)
test_s3_connection(logging.getLogger())
"
```

**Module**: [s3_parquet_exporter.py](s3_parquet_exporter.py)

---

## Support

**Questions?** See [../README.md](../README.md) for:
- System architecture
- Complete configuration reference
- InfluxDB schema details
- Grafana integration
- Web interface usage

**Issues?** Check:
1. [Troubleshooting](#troubleshooting) section above
2. Log files in `/src/logs/pcp_parser_python/`
3. Docker container status: `docker ps`

---

## License

[Add your license information here]
