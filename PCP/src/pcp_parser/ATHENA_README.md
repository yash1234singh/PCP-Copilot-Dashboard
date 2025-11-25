# AWS Athena Query Guide for PCP Metrics

Complete guide for querying PCP metrics stored in S3 using AWS Athena and Glue.

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Understanding the Architecture](#understanding-the-architecture)
4. [What is AWS Glue?](#what-is-aws-glue-data-catalog)
5. [Setup Steps](#setup-steps-detailed)
6. [IAM Permissions](#required-iam-permissions)
7. [Using the Scripts](#using-the-scripts)
8. [Athena Query Editor](#using-athena-query-editor)
9. [Athena Notebooks](#using-athena-notebooks-not-recommended)
10. [Troubleshooting](#troubleshooting)
11. [Cost Optimization](#cost-considerations)

---

## Overview

The Athena query system provides a complete workflow for querying PCP metrics data:

### Automated Setup Process

The script automatically executes these steps in order:

**Step 0: Permission Check** (Optional)
- Verify AWS IAM permissions for Athena, Glue, and S3
- Use `--check-permissions` flag to run this check

**Step 1: Database Setup**
- Check if database `fst_pcp_data` exists, if yes delete it
- Create fresh database `fst_pcp_data` with S3 location

**Step 2: Table Setup**
- Check if table `fst_pcp_data_table` exists, if yes delete it
- Create fresh table with complete schema (395+ columns)
- Uses Parquet format with SNAPPY compression

**Step 3: Partition Discovery**
- Run `MSCK REPAIR TABLE` to discover partitions from S3

**Step 4: Show Partitions**
- Display all discovered partitions for verification

**Step 5: Sample Query**
- Run a sample query to verify data is accessible

### Key Features

- **Clean Setup**: Automatically deletes and recreates database/table to avoid schema conflicts
- **Complete Schema**: Includes all 395+ PCP metrics columns
- **Standardized Location**: Uses dedicated S3 metrics path
- **Automatic Verification**: Runs sample query to confirm setup
- **Full Automation**: Single command setup and configuration

---

## Quick Start

### **Option 1: Using query_athena.sh (Recommended)**

```bash
# From src/ directory
cd src/

# Step 0: Check permissions first (recommended before first run)
./query_athena.sh --check-permissions

# Step 1-5: Setup database, table, and verify
./query_athena.sh --setup-only

# Or: Complete workflow (setup + query)
./query_athena.sh

# Query with custom time range
./query_athena.sh --start-time "2025-11-01 00:00:00" --end-time "2025-11-30 23:59:59"

# Export to CSV
./query_athena.sh --output results.csv
```

### **Option 2: Using Athena Query Editor**

1. Verify permissions (see [IAM Permissions](#required-iam-permissions))
2. Open AWS Console → Athena → Query Editor
3. Run the 5 SQL setup commands (see [Athena Query Editor](#using-athena-query-editor))
4. Start querying your data

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
-- Delete existing database if it exists
DROP DATABASE IF EXISTS fst_pcp_data CASCADE;

-- Create new database
CREATE DATABASE IF NOT EXISTS fst_pcp_data
COMMENT 'FST PCP Metrics Database'
LOCATION 's3://fst-pcp-data1/metrics/pcp/';
```

**What This Does**:
- Deletes existing `fst_pcp_data` database (if exists)
- Creates fresh logical database `fst_pcp_data`
- Associates it with dedicated S3 metrics location
- Does NOT move or copy any data

**Verify**: AWS Glue Console → Databases → See `fst_pcp_data`

---

### **Step 2: Create Glue Table**

**What**: Defines schema for your Parquet files

**SQL** (Run in Athena Query Editor):
```sql
-- Delete existing table if it exists
DROP TABLE IF EXISTS fst_pcp_data.fst_pcp_data_table;

-- Create new table with complete schema
CREATE EXTERNAL TABLE IF NOT EXISTS fst_pcp_data.fst_pcp_data_table (
    -- Data columns (from Parquet files) - 395+ metrics
    `timestamp` bigint,
    `hinv.ncpu` double,
    `hinv.physmem` double,
    `hinv.pagesize` double,
    `hinv.ndisk` double,
    `hinv.cpu.model_name-cpu0` string,
    -- ... (see query_athena.py for complete schema with all 395+ columns)
    `kernel.all.cpu.user` double,
    `kernel.all.cpu.sys` double,
    `kernel.all.cpu.idle` double,
    `mem.util.used` double,
    `mem.util.free` double,
    `disk.all.read` double,
    `disk.all.write` double,
    `network.interface.in.bytes-eth0` double,
    `network.interface.out.bytes-eth0` double,
    -- ... (full schema includes all PCP metrics)
    `__index_level_0__` bigint
)
PARTITIONED BY (
    -- Partition columns (from S3 folder structure)
    `year` string,
    `month` string,
    `day` string,
    `hour` string,
    `product_type` string,
    `serial_number` string
)
STORED AS PARQUET
LOCATION 's3://fst-pcp-data1/metrics/pcp/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
```

**Note**: The complete table schema with all 395+ columns is defined in `query_athena.py`. The schema includes:
- Hardware inventory metrics (hinv.*)
- CPU metrics (kernel.cpu.*, kernel.all.cpu.*)
- Memory metrics (mem.*)
- Disk metrics (disk.*)
- Network metrics (network.*)
- Filesystem metrics (filesys.*)
- And many more...

**What This Does**:
- Deletes existing `fst_pcp_data_table` (if exists)
- Defines complete table schema with all PCP metrics
- Maps to dedicated S3 metrics location
- Specifies Parquet format with SNAPPY compression
- Defines partition structure
- Registers in Glue Catalog

**Verify**: AWS Glue Console → Tables → See `fst_pcp_data_table`

---

### **Step 3: Discover Partitions**

**What**: Scans S3 to find all data partitions

**Why Needed**: S3 folders like `year=2025/month=11/` are partitions that Glue needs to know about

**SQL** (Run in Athena Query Editor):
```sql
MSCK REPAIR TABLE fst_pcp_data.fst_pcp_data_table;
```

**What This Does**:
- Scans S3 bucket at `s3://fst-pcp-data1/metrics/pcp/`
- Finds folders matching `year=X/month=Y/day=Z/...`
- Registers each combination as a partition
- Returns: "Partitions not in metastore: N"

**Verify**: AWS Glue Console → Tables → fst_pcp_data_table → Partitions tab

---

### **Step 4: Show Partitions**

**What**: Display all discovered partitions

**SQL** (Run in Athena Query Editor):
```sql
SHOW PARTITIONS fst_pcp_data.fst_pcp_data_table;
```

**What This Does**:
- Lists all partitions discovered in Step 3
- Helps verify that data was properly discovered

---

### **Step 5: Query Data**

**What**: Use SQL to query your Parquet files

**SQL** (Run in Athena Query Editor):
```sql
-- Sample query to check data
SELECT *
FROM fst_pcp_data.fst_pcp_data_table
LIMIT 10;

-- Filtered query with specific metrics
SELECT
    `timestamp`,
    `kernel.all.cpu.idle`,
    `kernel.all.cpu.user`,
    `mem.util.used`,
    `mem.util.free`
FROM fst_pcp_data.fst_pcp_data_table
WHERE product_type = 'SW_DEV_11'
  AND serial_number = '1235678'
ORDER BY `timestamp` DESC
LIMIT 100;
```

**What This Does**:
1. Athena reads table definition from Glue
2. Uses partition filters to find relevant S3 folders
3. Reads only matching Parquet files
4. Returns results

**Note**: Column names use backticks because they contain special characters (dots, dashes)

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

# Athena Configuration
ATHENA_DATABASE = 'fst_pcp_data'
ATHENA_TABLE = 'fst_pcp_data_table'
ATHENA_OUTPUT_LOCATION = 's3://fst-pcp-data1/athena-results/'
S3_DATA_LOCATION = 's3://fst-pcp-data1/metrics/pcp/'

# Query Filters
PRODUCT_TYPE = 'SW_DEV_11'
SERIAL_NUMBER = '1235678'

# Default time range (last 7 days)
DEFAULT_START_TIME = (datetime.now() - timedelta(days=7))
DEFAULT_END_TIME = datetime.now()

# Metrics to query (use backticks for special characters)
METRICS_TO_QUERY = [
    'timestamp',
    'kernel.all.cpu.idle',
    'kernel.all.cpu.user',
    'mem.util.used',
    'mem.util.free'
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
-- Drop existing database if it exists
DROP DATABASE IF EXISTS fst_pcp_data CASCADE;

-- Create new database
CREATE DATABASE IF NOT EXISTS fst_pcp_data
COMMENT 'FST PCP Metrics Database'
LOCATION 's3://fst-pcp-data1/metrics/pcp/';
```
Click **"Run"**

### **Step 3: Create Table**

**Note**: The complete schema with 395+ columns is in `query_athena.py`. Here's a simplified version:

```sql
-- Drop existing table if it exists
DROP TABLE IF EXISTS fst_pcp_data.fst_pcp_data_table;

-- Create new table (simplified - see query_athena.py for complete schema)
CREATE EXTERNAL TABLE IF NOT EXISTS fst_pcp_data.fst_pcp_data_table (
    `timestamp` bigint,
    `kernel.all.cpu.idle` DOUBLE,
    `kernel.all.cpu.user` DOUBLE,
    `mem.util.used` DOUBLE,
    `mem.util.free` DOUBLE,
    -- ... (395+ columns total, see query_athena.py for complete schema)
    `__index_level_0__` bigint
)
PARTITIONED BY (
    `year` STRING, `month` STRING, `day` STRING, `hour` STRING,
    `product_type` STRING, `serial_number` STRING
)
STORED AS PARQUET
LOCATION 's3://fst-pcp-data1/metrics/pcp/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
```
Click **"Run"**

**Recommendation**: Use `query_athena.py` script instead of manual SQL for the complete schema.

### **Step 4: Discover Partitions**

```sql
MSCK REPAIR TABLE fst_pcp_data.fst_pcp_data_table;
```
Click **"Run"**

### **Step 5: Show Partitions**

```sql
SHOW PARTITIONS fst_pcp_data.fst_pcp_data_table;
```
Click **"Run"**

### **Step 6: Query Data**

```sql
-- Sample query
SELECT *
FROM fst_pcp_data.fst_pcp_data_table
LIMIT 10;

-- Filtered query with specific metrics
SELECT
    `timestamp`,
    `kernel.all.cpu.idle`,
    `mem.util.used`
FROM fst_pcp_data.fst_pcp_data_table
WHERE product_type = 'SW_DEV_11'
  AND serial_number = '1235678'
ORDER BY `timestamp` DESC
LIMIT 100;
```
Click **"Run"**

### **Useful Queries**

**Check partitions**:
```sql
SHOW PARTITIONS fst_pcp_data.fst_pcp_data_table;
```

**Count rows**:
```sql
SELECT COUNT(*) FROM fst_pcp_data.fst_pcp_data_table;
```

**Note**: Use backticks (`) for column names with special characters (dots, dashes)

---

## Using Athena Notebooks (Not Recommended)

**Note**: Athena Notebooks have PySpark compatibility issues. We recommend using **Athena Query Editor** instead.

If you must use Notebooks, use `%%sql` magic:

```sql
%%sql

SELECT * FROM fst_pcp_data.fst_pcp_data_table LIMIT 100
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
   MSCK REPAIR TABLE fst_pcp_data.fst_pcp_data_table;
   SHOW PARTITIONS fst_pcp_data.fst_pcp_data_table;
   ```

2. **No data in S3**
   - Check: AWS S3 Console → `fst-pcp-data1` → `metrics/pcp/`
   - Ensure `ENABLE_S3_EXPORT=true` in docker-compose.yml
   - Process PCP archives to generate data

3. **Wrong filter values**
   - Check `product_type` and `serial_number` match your S3 folders
   - Check time range

---

### **Error: HIVE_PARTITION_SCHEMA_MISMATCH**

**Cause**: Table schema doesn't match Parquet file structure

**Fix**: Drop and recreate table (the script does this automatically)
```sql
DROP TABLE fst_pcp_data.fst_pcp_data_table;
-- Then run CREATE TABLE again with complete schema
```

Or run the script which handles this automatically:
```bash
./query_athena.sh --setup-only
```

---

### **Slow Query Performance**

**Optimization Tips**:

1. **Use partition filters**:
   ```sql
   WHERE product_type = 'SW_DEV_11'  -- Partition filter
     AND serial_number = '1235678'    -- Partition filter
     AND `timestamp` >= 1638316800    -- Filter on timestamp
   ```

2. **Limit columns**:
   ```sql
   SELECT `timestamp`, `kernel.all.cpu.idle`  -- Only needed columns
   FROM fst_pcp_data.fst_pcp_data_table
   ```

3. **Use LIMIT**:
   ```sql
   LIMIT 1000  -- Start small
   ```

4. **Check data scanned**:
   - Athena Query Editor shows "Data scanned" after query
   - Lower is better (and cheaper)

5. **Use backticks for column names**:
   - Always use backticks for columns with dots or dashes
   - Example: `` `kernel.all.cpu.idle` ``

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
# Option A: Use script (easiest - recommended)

# First: Check permissions
python3 query_athena.py --check-permissions
# or
./query_athena.sh --check-permissions

# Then: Run setup
./query_athena.sh --setup-only

# This automatically runs all 5 setup steps:
# 1. Delete and create database
# 2. Delete and create table with full schema
# 3. Discover partitions (MSCK REPAIR)
# 4. Show partitions
# 5. Run sample query

# Option B: Use Athena Query Editor
# First verify IAM permissions, then run SQL commands manually
# (see "Using Athena Query Editor" section)
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
./query_athena.sh --setup-only  # Runs complete setup including MSCK REPAIR TABLE
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

**Configuration**:
- **IAM User**: `arn:aws:iam::236132924050:user/pcp-data`
- **AWS Region**: `us-west-2`
- **S3 Bucket**: `fst-pcp-data1`
- **S3 Data Location**: `s3://fst-pcp-data1/metrics/pcp/`
- **S3 Results Location**: `s3://fst-pcp-data1/athena-results/`
- **Database**: `fst_pcp_data`
- **Table**: `fst_pcp_data_table`
- **Schema**: 395+ PCP metrics columns
- **Format**: Parquet with SNAPPY compression

**Required Permissions**: 14 total (5 Athena + 8 Glue + 5 S3)

**Key Points**:
- Use backticks for column names with special characters
- Database and table are automatically dropped and recreated on setup
- Complete schema includes all PCP metrics
- Dedicated S3 locations for data and query results

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

