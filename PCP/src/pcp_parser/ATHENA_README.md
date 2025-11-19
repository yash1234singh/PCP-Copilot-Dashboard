# AWS Athena Query Guide for PCP Metrics

Complete guide for querying PCP metrics stored in S3 using AWS Athena and Glue.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Understanding the Architecture](#understanding-the-architecture)
3. [What is AWS Glue?](#what-is-aws-glue-data-catalog)
4. [Setup Steps](#setup-steps-detailed)
5. [IAM Permissions](#required-iam-permissions)
6. [Using the Scripts](#using-the-scripts)
7. [Athena Query Editor](#using-athena-query-editor)
8. [Athena Notebooks](#using-athena-notebooks-not-recommended)
9. [Troubleshooting](#troubleshooting)
10. [Cost Optimization](#cost-considerations)

---

## Quick Start

### **Option 1: Using query_athena.sh (Recommended)**

```bash
# From src/ directory
cd src/

# First time setup + query
./query_athena.sh

# Or setup only
./query_athena.sh --setup-only

# Check permissions
./query_athena.sh --check-permissions

# Query with custom time range
./query_athena.sh --start-time "2025-11-01 00:00:00" --end-time "2025-11-30 23:59:59"

# Export to CSV
./query_athena.sh --output results.csv
```

### **Option 2: Using Athena Query Editor**

1. Open AWS Console → Athena → Query Editor
2. Run these 4 SQL commands (see [Athena Query Editor](#using-athena-query-editor))
3. Start querying your data

---

## Understanding the Architecture

### **How It Works**

```
┌─────────────────────────────────────────────────────────────────┐
│                     COMPLETE WORKFLOW                            │
└─────────────────────────────────────────────────────────────────┘

1. DATA STORAGE (You already have this)
   ┌──────────────────────────────────────┐
   │        Amazon S3 Bucket              │
   │    s3://fst-pcp-data1/               │
   │                                      │
   │  📁 year=2025/                       │
   │    📁 month=11/                      │
   │      📁 day=18/                      │
   │        📁 hour=01/                   │
   │          📁 product_type=SW_DEV_11/  │
   │            📁 serial_number=1235678/ │
   │              📄 data.parquet  ✅     │
   └──────────────────────────────────────┘
                     │
                     │ Points to
                     ▼
2. METADATA CATALOG (Setup required)
   ┌──────────────────────────────────────┐
   │       AWS Glue Data Catalog          │
   │                                      │
   │  📚 Database: pcp_metrics_db         │
   │    📋 Table: pcp_metrics             │
   │                                      │
   │    Stores:                           │
   │    - Column names & types            │
   │    - Partition structure             │
   │    - S3 location                     │
   │    - File format (Parquet)           │
   └──────────────────────────────────────┘
                     │
                     │ Uses
                     ▼
3. QUERY ENGINE
   ┌──────────────────────────────────────┐
   │         Amazon Athena                │
   │                                      │
   │  You write SQL:                      │
   │  SELECT * FROM pcp_metrics           │
   │  WHERE product_type = 'SW_DEV_11'    │
   │                                      │
   │  Athena:                             │
   │  - Reads Glue metadata               │
   │  - Scans only relevant S3 files      │
   │  - Returns results                   │
   └──────────────────────────────────────┘
```

---

## What is AWS Glue Data Catalog?

**AWS Glue Data Catalog** = Metadata storage for your data

Think of it like a library catalog:

| Traditional Library | AWS Glue Catalog |
|---------------------|------------------|
| Books on shelves | Parquet files in S3 |
| Card catalog (title, author, location) | Table schema (columns, types, S3 path) |
| Dewey Decimal System | Partitions (year/month/day) |
| You use catalog to find books | Athena uses catalog to query data |

### **What Glue Stores**

✅ **Database name**: `pcp_metrics_db` (logical grouping)
✅ **Table name**: `pcp_metrics`
✅ **Column definitions**: `timestamp TIMESTAMP`, `kernel_all_cpu_idle DOUBLE`, etc.
✅ **S3 location**: `s3://fst-pcp-data1/`
✅ **Partition columns**: `year`, `month`, `day`, `hour`, `product_type`, `serial_number`
✅ **File format**: Parquet
✅ **Compression**: Snappy

### **What Glue Does NOT Store**

❌ Your actual data (stays in S3)
❌ Query results
❌ Indexes (Athena scans files directly)

---

## Setup Steps (Detailed)

### **Step 1: Create Glue Database**

**What**: A namespace/folder to organize tables

**SQL** (Run in Athena Query Editor):
```sql
CREATE DATABASE IF NOT EXISTS pcp_metrics_db
COMMENT 'PCP Metrics Database'
LOCATION 's3://fst-pcp-data1/';
```

**What This Does**:
- Creates logical database `pcp_metrics_db`
- Associates it with S3 location
- Does NOT move or copy any data

**Verify**: AWS Glue Console → Databases → See `pcp_metrics_db`

---

### **Step 2: Create Glue Table**

**What**: Defines schema for your Parquet files

**SQL** (Run in Athena Query Editor):
```sql
CREATE EXTERNAL TABLE IF NOT EXISTS pcp_metrics_db.pcp_metrics (
    -- Data columns (from Parquet files)
    timestamp TIMESTAMP,
    kernel_all_cpu_idle DOUBLE,
    kernel_all_cpu_user DOUBLE,
    kernel_all_cpu_sys DOUBLE,
    kernel_all_cpu_nice DOUBLE,
    kernel_all_cpu_wait_total DOUBLE,
    kernel_all_cpu_irq_hard DOUBLE,
    kernel_all_cpu_irq_soft DOUBLE,
    kernel_all_cpu_steal DOUBLE,
    kernel_all_cpu_guest DOUBLE,
    mem_util_used DOUBLE,
    mem_util_free DOUBLE,
    mem_util_cached DOUBLE,
    mem_util_buffers DOUBLE,
    mem_util_shared DOUBLE,
    mem_util_available DOUBLE,
    disk_dev_read DOUBLE,
    disk_dev_write DOUBLE,
    disk_dev_read_bytes DOUBLE,
    disk_dev_write_bytes DOUBLE,
    network_interface_in_bytes DOUBLE,
    network_interface_out_bytes DOUBLE,
    network_interface_in_packets DOUBLE,
    network_interface_out_packets DOUBLE,
    network_interface_in_errors DOUBLE,
    network_interface_out_errors DOUBLE
)
PARTITIONED BY (
    -- Partition columns (from S3 folder structure)
    year STRING,
    month STRING,
    day STRING,
    hour STRING,
    product_type STRING,
    serial_number STRING
)
STORED AS PARQUET
LOCATION 's3://fst-pcp-data1/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
```

**What This Does**:
- Defines table schema
- Maps to S3 location
- Specifies Parquet format
- Defines partition structure
- Registers in Glue Catalog

**Verify**: AWS Glue Console → Tables → See `pcp_metrics`

---

### **Step 3: Discover Partitions**

**What**: Scans S3 to find all data partitions

**Why Needed**: S3 folders like `year=2025/month=11/` are partitions that Glue needs to know about

**SQL** (Run in Athena Query Editor):
```sql
MSCK REPAIR TABLE pcp_metrics_db.pcp_metrics;
```

**What This Does**:
- Scans S3 bucket
- Finds folders matching `year=X/month=Y/day=Z/...`
- Registers each combination as a partition
- Returns: "Partitions not in metastore: N"

**Verify**: AWS Glue Console → Tables → pcp_metrics → Partitions tab

---

### **Step 4: Query Data**

**What**: Use SQL to query your Parquet files

**SQL** (Run in Athena Query Editor):
```sql
SELECT
    timestamp,
    kernel_all_cpu_idle,
    kernel_all_cpu_user,
    mem_util_used,
    mem_util_free
FROM pcp_metrics_db.pcp_metrics
WHERE product_type = 'SW_DEV_11'
  AND serial_number = '1235678'
  AND timestamp >= TIMESTAMP '2025-11-01 00:00:00'
ORDER BY timestamp DESC
LIMIT 100;
```

**What This Does**:
1. Athena reads table definition from Glue
2. Uses partition filters to find relevant S3 folders
3. Reads only matching Parquet files
4. Returns results

---

## Required IAM Permissions

### **Complete IAM Policy**

Add this policy to your IAM user `pcp-data`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AthenaQueryPermissions",
      "Effect": "Allow",
      "Action": [
        "athena:StartQueryExecution",
        "athena:GetQueryExecution",
        "athena:GetQueryResults",
        "athena:StopQueryExecution",
        "athena:GetWorkGroup"
      ],
      "Resource": "*"
    },
    {
      "Sid": "GluePermissions",
      "Effect": "Allow",
      "Action": [
        "glue:CreateDatabase",
        "glue:GetDatabase",
        "glue:CreateTable",
        "glue:GetTable",
        "glue:UpdateTable",
        "glue:DeleteTable",
        "glue:GetPartitions",
        "glue:BatchCreatePartition"
      ],
      "Resource": "*"
    },
    {
      "Sid": "S3QueryResultsPermissions",
      "Effect": "Allow",
      "Action": [
        "s3:GetBucketLocation",
        "s3:GetObject",
        "s3:ListBucket",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": [
        "arn:aws:s3:::fst-pcp-data1",
        "arn:aws:s3:::fst-pcp-data1/*"
      ]
    }
  ]
}
```

### **How to Add Policy**

**Method 1: AWS Console**
1. Go to IAM Console: https://console.aws.amazon.com/iam/
2. Click "Users" → Select "pcp-data"
3. Click "Add permissions" → "Create inline policy"
4. Click "JSON" tab
5. Paste policy above
6. Click "Review policy"
7. Name: `AthenaQueryPolicy`
8. Click "Create policy"

**Method 2: AWS CLI**
```bash
# Save policy to file
cat > athena-policy.json <<'EOF'
[paste policy above]
EOF

# Attach to user
aws iam put-user-policy \
  --user-name pcp-data \
  --policy-name AthenaQueryPolicy \
  --policy-document file://athena-policy.json
```

### **Check Permissions**

```bash
./query_athena.sh --check-permissions
```

---

## Using the Scripts

### **query_athena.sh - Main Script**

Complete workflow automation with credential checking, permission verification, and query execution.

**Basic Usage**:
```bash
cd src/

# Setup and query (auto-detects first run)
./query_athena.sh

# Setup only
./query_athena.sh --setup-only

# Check permissions
./query_athena.sh --check-permissions

# Custom query
./query_athena.sh \
  --start-time "2025-11-01 00:00:00" \
  --end-time "2025-11-30 23:59:59" \
  --product-type "SW_DEV_11" \
  --limit 5000

# Export to CSV
./query_athena.sh --output results.csv

# Get help
./query_athena.sh --help
```

**What It Does**:
1. ✅ Checks Docker container is running
2. ✅ Verifies AWS credentials in .env
3. ✅ Quick S3 access test
4. ✅ Copies scripts to container
5. ✅ Runs query_athena.py
6. ✅ Shows helpful error messages

---

### **query_athena.py - Python Script**

Backend script that handles Athena operations.

**Configuration** (Edit lines 34-61 in script):
```python
# AWS Configuration
AWS_REGION = 'us-west-2'
S3_BUCKET_NAME = 'fst-pcp-data1'
S3_KEY_PREFIX = ''

# Query Filters
PRODUCT_TYPE = 'SW_DEV_11'
SERIAL_NUMBER = '1235678'

# Default time range (last 7 days)
DEFAULT_START_TIME = (datetime.now() - timedelta(days=7))
DEFAULT_END_TIME = datetime.now()

# Metrics to query
METRICS_TO_QUERY = [
    'timestamp',
    'kernel_all_cpu_idle',
    'kernel_all_cpu_user',
    'mem_util_used',
    'mem_util_free'
]
```

**Direct Usage**:
```bash
docker exec pcp_parser_python python3 query_athena.py --setup-only
docker exec pcp_parser_python python3 query_athena.py
```

---

### **check_athena_permissions.py - Permission Checker**

Tests all required AWS permissions.

**Usage**:
```bash
./query_athena.sh --check-permissions
```

**Tests**:
1. ✅ AWS credentials
2. ✅ Athena query permissions
3. ✅ Glue database/table permissions
4. ✅ S3 read/write permissions

**Output**:
```
✓ AWS credentials found
✓ athena:StartQueryExecution - ALLOWED
✓ glue:CreateDatabase - ALLOWED
✓ s3:PutObject - ALLOWED

🎉 ALL PERMISSIONS ARE CONFIGURED CORRECTLY!
```

---

## Using Athena Query Editor

**AWS Athena Query Editor** is the simplest way to query your data.

### **Step 1: Open Query Editor**

1. AWS Console → Search "Athena"
2. Click "Query editor"
3. Configure query result location (first time only):
   - Settings → Manage
   - Query result location: `s3://fst-pcp-data1/athena-results/`
   - Save

### **Step 2: Create Database**

```sql
CREATE DATABASE IF NOT EXISTS pcp_metrics_db;
```
Click **"Run"**

### **Step 3: Create Table**

```sql
CREATE EXTERNAL TABLE IF NOT EXISTS pcp_metrics_db.pcp_metrics (
    timestamp TIMESTAMP,
    kernel_all_cpu_idle DOUBLE,
    kernel_all_cpu_user DOUBLE,
    mem_util_used DOUBLE,
    mem_util_free DOUBLE,
    disk_dev_read DOUBLE,
    disk_dev_write DOUBLE
)
PARTITIONED BY (
    year STRING, month STRING, day STRING, hour STRING,
    product_type STRING, serial_number STRING
)
STORED AS PARQUET
LOCATION 's3://fst-pcp-data1/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
```
Click **"Run"**

### **Step 4: Discover Partitions**

```sql
MSCK REPAIR TABLE pcp_metrics_db.pcp_metrics;
```
Click **"Run"**

### **Step 5: Query Data**

```sql
SELECT
    timestamp,
    kernel_all_cpu_idle,
    mem_util_used
FROM pcp_metrics_db.pcp_metrics
WHERE product_type = 'SW_DEV_11'
  AND serial_number = '1235678'
ORDER BY timestamp DESC
LIMIT 100;
```
Click **"Run"**

### **Useful Queries**

**Check partitions**:
```sql
SHOW PARTITIONS pcp_metrics_db.pcp_metrics;
```

**Count rows**:
```sql
SELECT COUNT(*) FROM pcp_metrics_db.pcp_metrics;
```

**Hourly aggregates**:
```sql
SELECT
    DATE_TRUNC('hour', timestamp) as hour,
    AVG(kernel_all_cpu_idle) as avg_cpu_idle,
    AVG(mem_util_used) as avg_memory,
    COUNT(*) as samples
FROM pcp_metrics_db.pcp_metrics
WHERE product_type = 'SW_DEV_11'
GROUP BY DATE_TRUNC('hour', timestamp)
ORDER BY hour DESC
LIMIT 24;
```

---

## Using Athena Notebooks (Not Recommended)

**Note**: Athena Notebooks have PySpark compatibility issues. We recommend using **Athena Query Editor** instead.

If you must use Notebooks, use `%%sql` magic:

```sql
%%sql

SELECT * FROM pcp_metrics_db.pcp_metrics LIMIT 100
```

See [athena_notebook_simple.md](athena_notebook_simple.md) for details.

---

## Troubleshooting

### **Error: AccessDeniedException**

**Error**:
```
AccessDeniedException: You are not authorized to perform: athena:StartQueryExecution
```

**Fix**: Add IAM policy (see [Required IAM Permissions](#required-iam-permissions))

**Check**:
```bash
./query_athena.sh --check-permissions
```

---

### **Error: Table not found**

**Cause**: Database/table not created yet

**Fix**: Run setup:
```bash
./query_athena.sh --setup-only
```

---

### **Query Returns 0 Rows**

**Possible Causes**:

1. **No partitions discovered**
   ```sql
   MSCK REPAIR TABLE pcp_metrics_db.pcp_metrics;
   SHOW PARTITIONS pcp_metrics_db.pcp_metrics;
   ```

2. **No data in S3**
   - Check: AWS S3 Console → `fst-pcp-data1`
   - Ensure `ENABLE_S3_EXPORT=true` in docker-compose.yml
   - Process PCP archives to generate data

3. **Wrong filter values**
   - Check `product_type` and `serial_number` match your S3 folders
   - Check time range

---

### **Error: HIVE_PARTITION_SCHEMA_MISMATCH**

**Cause**: Table schema doesn't match Parquet file structure

**Fix**: Drop and recreate table
```sql
DROP TABLE pcp_metrics_db.pcp_metrics;
-- Then run CREATE TABLE again
```

---

### **Slow Query Performance**

**Optimization Tips**:

1. **Use partition filters**:
   ```sql
   WHERE product_type = 'SW_DEV_11'  -- Partition filter
     AND serial_number = '1235678'    -- Partition filter
     AND timestamp >= '2025-11-01'
   ```

2. **Limit columns**:
   ```sql
   SELECT timestamp, kernel_all_cpu_idle  -- Only needed columns
   FROM pcp_metrics_db.pcp_metrics
   ```

3. **Use LIMIT**:
   ```sql
   LIMIT 1000  -- Start small
   ```

4. **Check data scanned**:
   - Athena Query Editor shows "Data scanned" after query
   - Lower is better (and cheaper)

---

## Cost Considerations

### **Pricing**

| Service | Cost | When Charged |
|---------|------|--------------|
| **S3 Storage** | ~$0.023/GB/month | Storing Parquet files |
| **Glue Catalog** | First 1M objects free, then $1/100K | Storing metadata |
| **Athena Queries** | $5/TB scanned | Running SELECT queries |

### **Cost Optimization**

✅ **Use Partitions**: Filter on `product_type`, `serial_number`, `year`, `month` to scan less data
✅ **Parquet Format**: Already using Parquet (5-10x smaller than CSV)
✅ **Select Specific Columns**: Don't use `SELECT *`
✅ **Use LIMIT**: Start with small result sets
✅ **Time Filters**: Always specify time ranges

**Example Cost**:
- Data scanned: 100 GB
- Cost: 100 GB × $5/TB = **$0.50**

---

## Summary Workflow

### **One-Time Setup**

```bash
# Option A: Use script (easiest)
./query_athena.sh --setup-only

# Option B: Use Athena Query Editor
# Run 3 SQL commands: CREATE DATABASE, CREATE TABLE, MSCK REPAIR
```

### **Query Data**

```bash
# Default query (last 7 days)
./query_athena.sh

# Custom query
./query_athena.sh \
  --start-time "2025-11-01 00:00:00" \
  --end-time "2025-11-30 23:59:59" \
  --output results.csv
```

### **When You Add New Data**

```bash
# Discover new partitions
./query_athena.sh --setup-only  # Runs MSCK REPAIR TABLE
```

---

## Related Files

| File | Purpose |
|------|---------|
| `query_athena.sh` | Main script - complete workflow |
| `query_athena.py` | Python backend for Athena queries |
| `check_athena_permissions.py` | Permission verification tool |
| `athena_notebook_simple.md` | Athena Notebook guide (if needed) |

---

## Quick Reference

**IAM User**: `arn:aws:iam::236132924050:user/pcp-data`
**AWS Region**: `us-west-2`
**S3 Bucket**: `fst-pcp-data1`
**Database**: `pcp_metrics_db`
**Table**: `pcp_metrics`

**Required Permissions**: 14 total (5 Athena + 8 Glue + 5 S3)

---

## Support

**Check permissions**:
```bash
./query_athena.sh --check-permissions
```

**Get help**:
```bash
./query_athena.sh --help
```

**Documentation**:
- This file: Complete Athena guide
- [pcp_parser/README.md](README.md) - S3 Parquet export setup
- [TEST_S3_README.md](TEST_S3_README.md) - S3 write testing

---

**You're all set! Run `./query_athena.sh` to start querying your PCP metrics data.** 🎉
