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
# Output control (NEW: Flag-driven architecture)
SAVE_CSV_OUTPUT=true              # Save CSV for debugging
ENABLE_INFLUXDB_WRITE=true        # Enable InfluxDB writes
ENABLE_S3_EXPORT=false            # Enable S3 Parquet export
ENABLE_SNAME_PROCESSING=false     # Enable proc.psinfo.sname

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

## Processing Architecture (Refactored)

The parser uses a **5-step pipeline architecture** for efficient data processing:

### High-Level Flow

```
Archive → Extract → Validate Metrics → Process & Export → Move to Processed
```

### Data Processing Pipeline (process_and_export_metrics)

The new refactored architecture separates data collection from export mechanisms:

**Step 1: Collect Metrics Data** (`collect_metrics_data`)
- Runs `pmrep` to extract CSV data from PCP archive
- Parses CSV into pandas DataFrame (NO InfluxDB processing yet)
- Returns raw DataFrame ready for multiple export formats
- **Key Optimization**: Data is collected once and reused for all exports

**Step 2: Save CSV Output** (`save_csv_output`)
- **Only runs if** `SAVE_CSV_OUTPUT=true`
- Saves DataFrame to `/src/logs/pcp_parser/csv_output/`
- Filename format: `pmrep_{archive_name}_{timestamp}.csv`
- **Performance**: Skipped entirely when disabled (no I/O overhead)

**Step 3: Write to InfluxDB** (`write_to_influxdb`)
- **Only runs if** `ENABLE_INFLUXDB_WRITE=true`
- Checks flag FIRST before any InfluxDB processing
- Converts DataFrame to line protocol using `dataframe_to_line_protocol()`
- Writes in batches using async write API
- **Performance**: 30-40% CPU savings when disabled (no conversion overhead)

**Step 4: Export to S3 Parquet** (`export_to_s3_parquet_wrapper`)
- **Only runs if** `ENABLE_S3_EXPORT=true`
- Adds partition columns (year, month, day, hour, product_type, serial_number)
- Converts DataFrame to Parquet format using PyArrow
- Uploads to S3 with Hive-style partitioning
- **Performance**: Works directly with DataFrame (no intermediate CSV file)

**Step 5: Process proc.psinfo.sname** (if enabled)
- **Only runs if** `ENABLE_SNAME_PROCESSING=true`
- Collects process state data in parallel
- Exports to InfluxDB (only if `ENABLE_INFLUXDB_WRITE=true`)
- Tracks states: R (Running), D (Blocked), S (Sleeping), I (Idle), Z (Zombie), T (Stopped)

### Key Architecture Benefits

✅ **No Wasteful Processing**: Each export format only processes when enabled
✅ **DataFrame Reusability**: Collect data once, export to multiple formats
✅ **Flag-Driven**: All processing controlled by environment flags
✅ **Performance**: 30-40% CPU savings when InfluxDB writes disabled
✅ **Separation of Concerns**: Each export format has its own function

### Legacy Function (Deprecated)

`export_to_influxdb()` - **DEPRECATED**: This function is kept for backward compatibility but should not be used. It performs wasteful processing by converting to InfluxDB format even when writes are disabled. Use `process_and_export_metrics()` instead.

---

** Architecture **

```python
process_and_export_metrics()  # Flag-driven, modular pipeline
  ├─ collect_metrics_data()          # Step 1: Collect once
  ├─ save_csv_output()                # Step 2: Only if SAVE_CSV_OUTPUT=true
  ├─ write_to_influxdb()              # Step 3: Only if ENABLE_INFLUXDB_WRITE=true
  ├─ export_to_s3_parquet_wrapper()   # Step 4: Only if ENABLE_S3_EXPORT=true
  └─ Process proc.psinfo.sname        # Step 5: Only if ENABLE_SNAME_PROCESSING=true
```
- ✅ Checks flags BEFORE processing (no wasteful conversion)
- ✅ Reuses DataFrame for all exports (collect once, export many times)
- ✅ Modular functions (easy to test and maintain)
- ✅ S3 export works directly with DataFrame (no intermediate file)



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

### Main Processing Functions

| Function | Purpose | File Location |
|----------|---------|---------------|
| `process_archive()` | Main archive processing orchestrator | [pcp_parser.py:1851](pcp_parser.py#L1851) |
| `get_available_metrics()` | Metric discovery & validation | [pcp_parser.py:357](pcp_parser.py#L357) |
| `validate_metrics_parallel()` | Parallel metric validation (100 workers) | [pcp_parser.py:165](pcp_parser.py#L165) |

### Data Processing Pipeline 

| Function | Purpose | File Location |
|----------|---------|---------------|
| `process_and_export_metrics()` | **Main orchestrator** - 5-step pipeline | [pcp_parser.py:1261](pcp_parser.py#L1261) |
| `collect_metrics_data()` | Step 1: Collect data in DataFrame | [pcp_parser.py:969](pcp_parser.py#L969) |
| `save_csv_output()` | Step 2: Save CSV (if enabled) | [pcp_parser.py:1048](pcp_parser.py#L1048) |
| `write_to_influxdb()` | Step 3: Write to InfluxDB (if enabled) | [pcp_parser.py:1096](pcp_parser.py#L1096) |
| `export_to_s3_parquet_wrapper()` | Step 4: Export to S3 Parquet (if enabled) | [pcp_parser.py:1187](pcp_parser.py#L1187) |

### Helper Functions

| Function | Purpose | File Location |
|----------|---------|---------------|
| `parse_csv_with_pandas()` | Parse CSV using pandas (vectorized) | [pcp_parser.py:759](pcp_parser.py#L759) |
| `dataframe_to_line_protocol()` | Convert DataFrame to InfluxDB line protocol | [pcp_parser.py:791](pcp_parser.py#L791) |
| `parse_proc_psinfo_sname_from_process()` | Process state parsing | [pcp_parser.py:561](pcp_parser.py#L561) |
| `export_proc_sname_to_influxdb()` | Process state export to InfluxDB | [pcp_parser.py:721](pcp_parser.py#L721) |

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

### Key Log Sections (New Architecture)

```
[FLOW] === PHASE 1: ARCHIVE EXTRACTION ===
[FLOW] ✓ Extracted in 2.34s

[FLOW] === PHASE 2: METRIC VALIDATION ===
Parallel validation: 2000 metrics with 100 workers
✓ Found 1850 valid metrics

[FLOW] === PHASE 3: DATA EXPORT ===
================================================================================
STARTING METRICS PROCESSING AND EXPORT
================================================================================
Export configuration:
  - PANDAS_AVAILABLE: True
  - SAVE_CSV_OUTPUT: True
  - ENABLE_INFLUXDB_WRITE: True
  - ENABLE_S3_EXPORT: False
  - ENABLE_SNAME_PROCESSING: False

STEP 1: Collecting metrics data...
===== COLLECTING METRICS DATA =====
✓ CSV data collected (15234567 bytes)
✓ Data collected: 3600 rows, 1850 metrics

STEP 2: Saving CSV output (if enabled)...
============================================================
SAVING CSV OUTPUT
============================================================
✓ CSV saved: 14.53 MB

STEP 3: Writing to InfluxDB (if enabled)...
============================================================
WRITING TO INFLUXDB
============================================================
✓ Converted to 245000 line protocol entries
✓ Successfully wrote 245000 points to InfluxDB

STEP 4: Exporting to S3 Parquet (if enabled)...
S3 export disabled (ENABLE_S3_EXPORT=false)

STEP 5: Processing proc.psinfo.sname (if enabled)...
proc.psinfo.sname processing disabled (ENABLE_SNAME_PROCESSING=false)

================================================================================
METRICS PROCESSING AND EXPORT COMPLETE
================================================================================
✓ Data rows processed: 3600
✓ Metrics columns: 1850
✓ CSV output: /src/logs/pcp_parser/csv_output/pmrep_archive_20251119.csv
✓ InfluxDB: Data written

⏱️  TOTAL PROCESSING TIME: 1 minutes 45.23 seconds
   ├─ Extraction: 2.34s
   ├─ Validation: 18.50s
   └─ Export: 84.39s
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
Create a user in IAM role 


![alt text](image.png)
Update the .env file with 
AWS_ACCESS_KEY_ID=AK****************2
AWS_SECRET_ACCESS_KEY=hD***********************************GH


or Prefer (limited IAM policy):

Complete IAM Policy (JSON)
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3ParquetDataReadWrite",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket",
        "s3:GetBucketLocation",
        "s3:ListBucketVersions"
      ],
      "Resource": [
        "arn:aws:s3:::fst-pcp-data1",
        "arn:aws:s3:::fst-pcp-data1/*"
      ]
    },
    {
      "Sid": "AthenaQueryExecution",
      "Effect": "Allow",
      "Action": [
        "athena:StartQueryExecution",
        "athena:GetQueryExecution",
        "athena:GetQueryResults",
        "athena:StopQueryExecution",
        "athena:GetWorkGroup",
        "athena:ListQueryExecutions",
        "athena:BatchGetQueryExecution"
      ],
      "Resource": [
        "arn:aws:athena:us-west-2:*:workgroup/primary",
        "arn:aws:athena:us-west-2:*:workgroup/*"
      ]
    },
    {
      "Sid": "GlueCatalogDatabaseOperations",
      "Effect": "Allow",
      "Action": [
        "glue:CreateDatabase",
        "glue:GetDatabase",
        "glue:UpdateDatabase",
        "glue:DeleteDatabase",
        "glue:GetDatabases"
      ],
      "Resource": [
        "arn:aws:glue:us-west-2:*:catalog",
        "arn:aws:glue:us-west-2:*:database/fst_pcp_data"
      ]
    },
    {
      "Sid": "GlueCatalogTableOperations",
      "Effect": "Allow",
      "Action": [
        "glue:CreateTable",
        "glue:GetTable",
        "glue:UpdateTable",
        "glue:DeleteTable",
        "glue:GetTables",
        "glue:BatchCreatePartition",
        "glue:CreatePartition",
        "glue:GetPartition",
        "glue:GetPartitions",
        "glue:UpdatePartition",
        "glue:DeletePartition",
        "glue:BatchDeletePartition",
        "glue:BatchGetPartition"
      ],
      "Resource": [
        "arn:aws:glue:us-west-2:*:catalog",
        "arn:aws:glue:us-west-2:*:database/fst_pcp_data",
        "arn:aws:glue:us-west-2:*:table/fst_pcp_data/*"
      ]
    },
    {
      "Sid": "AthenaQueryResultsReadWrite",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:ListBucket",
        "s3:DeleteObject"
      ],
      "Resource": [
        "arn:aws:s3:::fst-pcp-data1/athena-results",
        "arn:aws:s3:::fst-pcp-data1/athena-results/*"
      ]
    }
  ]
}



Policy Breakdown by Use Case


1. S3 Parquet Write Operations (Statement 1)
Allows your application to write Parquet files to S3 with the new partitioning scheme: Permissions:
s3:PutObject - Upload Parquet files
s3:GetObject - Read uploaded files (for verification)
s3:DeleteObject - Delete old/test files
s3:ListBucket - List objects in bucket
s3:GetBucketLocation - Get bucket region
s3:ListBucketVersions - List object versions (if versioning enabled)
Resources:
arn:aws:s3:::fst-pcp-data1 - Bucket-level operations
arn:aws:s3:::fst-pcp-data1/* - Object-level operations
Writes to:
s3://fst-pcp-data1/
└── product_type=ERIC_TEST/
    └── serial_number=4311/
        └── year=2025/month=11/day=25/hour=14/
            └── data_20251125_143045.parquet
2. Athena Query Execution (Statement 2)
Allows running SQL queries via Athena: Permissions:
athena:StartQueryExecution - Start queries (SELECT, CREATE, MSCK REPAIR)
athena:GetQueryExecution - Get query status
athena:GetQueryResults - Retrieve query results
athena:StopQueryExecution - Cancel running queries
athena:GetWorkGroup - Access workgroup settings
athena:ListQueryExecutions - List query history
athena:BatchGetQueryExecution - Get multiple query statuses
Resources:
Workgroup: primary (default Athena workgroup)
Can be changed to specific workgroup ARN if needed
3. Glue Catalog - Database Operations (Statement 3)
Allows creating and managing Athena databases: Permissions:
glue:CreateDatabase - Create database (e.g., fst_pcp_data)
glue:GetDatabase - Read database metadata
glue:UpdateDatabase - Modify database properties
glue:DeleteDatabase - Delete database (if needed)
glue:GetDatabases - List all databases
Resources:
arn:aws:glue:us-west-2:*:catalog - Glue catalog access
arn:aws:glue:us-west-2:*:database/fst_pcp_data - Specific database
Used for:
CREATE DATABASE IF NOT EXISTS fst_pcp_data
LOCATION 's3://fst-pcp-data1/metrics/pcp/';
4. Glue Catalog - Table & Partition Operations (Statement 4)
Allows creating tables and managing partitions (MSCK REPAIR): Permissions:
glue:CreateTable - Create Athena external table
glue:GetTable - Read table metadata
glue:UpdateTable - Modify table schema
glue:DeleteTable - Drop tables
glue:GetTables - List tables in database
glue:BatchCreatePartition - MSCK REPAIR TABLE (auto-discover partitions)
glue:CreatePartition - Add single partition
glue:GetPartition - Read partition metadata
glue:GetPartitions - List all partitions
glue:UpdatePartition - Modify partition metadata
glue:DeletePartition - Remove partition
glue:BatchDeletePartition - Remove multiple partitions
glue:BatchGetPartition - Get multiple partition details
Resources:
Catalog and database (same as above)
arn:aws:glue:us-west-2:*:table/fst_pcp_data/* - All tables in database
Used for:
-- Create table with new partitioning scheme
CREATE EXTERNAL TABLE fst_pcp_data_table (...)
PARTITIONED BY (
    product_type string,
    serial_number string,
    year string,
    month string,
    day string,
    hour string
)
LOCATION 's3://fst-pcp-data1/metrics/pcp/';

-- Auto-discover partitions
MSCK REPAIR TABLE fst_pcp_data_table;

-- Show discovered partitions
SHOW PARTITIONS fst_pcp_data_table;
5. Athena Query Results Storage (Statement 5)
Athena stores query results in S3 - requires separate permissions: Permissions:
s3:PutObject - Write query results
s3:GetObject - Read query results
s3:ListBucket - List result files
s3:DeleteObject - Clean up old results
Resources:
arn:aws:s3:::fst-pcp-data1/athena-results - Query results folder
arn:aws:s3:::fst-pcp-data1/athena-results/* - Result files


### Features

✅ Automatic partitioning by product_type, serial_number, date (year/month/day/hour)
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
  s3://fst-pcp-data1/test/product_type=SW_DEV_11/serial_number=1235678/
    year=2025/month=11/day=19/hour=01/test_20251119_014640.parquet
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
    └── product_type=SW_DEV_11/
        └── serial_number=1235678/
            └── year=2025/month=11/day=19/hour=01/
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
└── product_type=SERVER1/serial_number=1234/year=2025/month=11/day=13/hour=14/
    └── data_20251113_143045.parquet
```

### Querying with AWS Athena

```sql
CREATE EXTERNAL TABLE pcp_metrics (
    timestamp TIMESTAMP,
    kernel_all_cpu_idle DOUBLE,
    mem_util_used DOUBLE
)
PARTITIONED BY (product_type, serial_number, year, month, day, hour)
STORED AS PARQUET
LOCATION 's3://your-bucket/time-series-data/';

MSCK REPAIR TABLE pcp_metrics;

SELECT * FROM pcp_metrics
WHERE product_type='SERVER1' AND serial_number='1234'
  AND year='2025' AND month='11' AND day='13' LIMIT 100;
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

## License

[Add your license information here]
