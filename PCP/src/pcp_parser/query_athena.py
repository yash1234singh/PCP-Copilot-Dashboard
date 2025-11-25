#!/usr/bin/env python3
"""
AWS Athena Query Script for PCP Metrics

This script queries PCP metrics stored in S3 Parquet format using AWS Athena.
It allows filtering by time range, product type, and serial number.

Usage:
    # Check IAM permissions
    python3 query_athena.py --check-permissions

    # Default configuration (reads from script)
    python3 query_athena.py

    # Custom parameters
    python3 query_athena.py --start-time "2025-11-01 00:00:00" --end-time "2025-11-30 23:59:59"

    # Export to CSV
    python3 query_athena.py --output metrics_output.csv

    # Show only summary
    python3 query_athena.py --summary-only

Features:
    - IAM permission checking
    - Automatic Athena table creation (if not exists)
    - Partition discovery and repair
    - Time range filtering
    - Product type and serial number filtering
    - Export results to CSV
    - Summary statistics
"""

import os
import sys
import time
import boto3
import argparse
import pandas as pd
from datetime import datetime, timedelta
from botocore.exceptions import ClientError, NoCredentialsError


# =============================================================================
# CONFIGURATION SECTION - CUSTOMIZE THESE VALUES
# =============================================================================

# AWS Configuration
AWS_REGION = os.getenv('AWS_REGION', 'us-west-2')
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME', 'fst-pcp-data1')
S3_KEY_PREFIX = os.getenv('S3_KEY_PREFIX', '')  # Empty = bucket root

# Athena Configuration
ATHENA_DATABASE = 'fst_pcp_data'
ATHENA_TABLE = 'fst_pcp_data_table'
ATHENA_OUTPUT_LOCATION = 's3://fst-pcp-data1/athena-results/'  # Query results location
S3_DATA_LOCATION = 's3://fst-pcp-data1/metrics/pcp/'

# Query Filters - FILL THESE based on current sample data
PRODUCT_TYPE = os.getenv('PRODUCT_TYPE', 'ERIC_TEST')
SERIAL_NUMBER = os.getenv('SERIAL_NUMBER', '4311')

# Default time range (last 7 days)
DEFAULT_START_TIME = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
DEFAULT_END_TIME = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# Metrics to query (customize based on your needs)
METRICS_TO_QUERY = [
    'timestamp',
    'kernel_all_cpu_idle',
    'kernel_all_cpu_user',
    'kernel_all_cpu_sys',
    'mem_util_used',
    'mem_util_free',
    'disk_dev_read',
    'disk_dev_write',
    'network_interface_in_bytes',
    'network_interface_out_bytes'
]

# =============================================================================


class PermissionChecker:
    """Check AWS permissions for Athena operations"""

    def __init__(self):
        self.region = os.getenv('AWS_REGION', 'us-west-2')
        self.bucket = os.getenv('S3_BUCKET_NAME', 'fst-pcp-data1')
        self.tests_passed = 0
        self.tests_failed = 0
        self.results = []

    def print_header(self):
        """Print header"""
        print("=" * 70)
        print("AWS Athena Permissions Checker")
        print("=" * 70)
        print()
        print("This script checks if your AWS credentials have the required")
        print("permissions to use AWS Athena for querying PCP metrics.")
        print()
        print(f"Region: {self.region}")
        print(f"Bucket: {self.bucket}")
        print()
        print("=" * 70)
        print()

    def check_credentials(self):
        """Check if AWS credentials are configured"""
        print("1️⃣  Checking AWS Credentials...")
        print("-" * 70)

        try:
            access_key = os.getenv('AWS_ACCESS_KEY_ID')
            secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')

            if not access_key or not secret_key:
                print("✗ FAILED: AWS credentials not found")
                print("  Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env")
                self.tests_failed += 1
                self.results.append(("Credentials", False, "Not found"))
                return False

            # Try to get caller identity
            sts = boto3.client('sts', region_name=self.region)
            identity = sts.get_caller_identity()

            print(f"✓ AWS credentials found")
            print(f"  Account: {identity['Account']}")
            print(f"  User ARN: {identity['Arn']}")
            print()

            self.tests_passed += 1
            self.results.append(("Credentials", True, identity['Arn']))
            return True

        except NoCredentialsError:
            print("✗ FAILED: No AWS credentials found")
            self.tests_failed += 1
            self.results.append(("Credentials", False, "No credentials"))
            return False
        except Exception as e:
            print(f"✗ FAILED: {e}")
            self.tests_failed += 1
            self.results.append(("Credentials", False, str(e)))
            return False

    def check_athena_permissions(self):
        """Check Athena permissions"""
        print("2️⃣  Checking Athena Permissions...")
        print("-" * 70)

        athena = boto3.client('athena', region_name=self.region)

        # Test StartQueryExecution
        try:
            print("Testing athena:StartQueryExecution...")
            # Simple SELECT 1 query (will fail if no permissions)
            response = athena.start_query_execution(
                QueryString='SELECT 1',
                ResultConfiguration={
                    'OutputLocation': f's3://{self.bucket}/athena-test/'
                }
            )
            query_id = response['QueryExecutionId']
            print(f"✓ athena:StartQueryExecution - ALLOWED")

            # Test GetQueryExecution
            print("Testing athena:GetQueryExecution...")
            athena.get_query_execution(QueryExecutionId=query_id)
            print(f"✓ athena:GetQueryExecution - ALLOWED")

            # Test GetQueryResults
            print("Testing athena:GetQueryResults...")
            athena.get_query_results(QueryExecutionId=query_id, MaxResults=1)
            print(f"✓ athena:GetQueryResults - ALLOWED")

            print()
            print("✓ PASSED: All Athena permissions are available")
            print()

            self.tests_passed += 1
            self.results.append(("Athena Permissions", True, "All allowed"))
            return True

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error']['Message']

            if 'AccessDenied' in error_code or 'NotAuthorized' in error_msg:
                print(f"✗ FAILED: Access Denied")
                print(f"  Error: {error_msg}")
                print()
                self.tests_failed += 1
                self.results.append(("Athena Permissions", False, "Access Denied"))
                return False
            else:
                print(f"✗ FAILED: {error_msg}")
                print()
                self.tests_failed += 1
                self.results.append(("Athena Permissions", False, error_code))
                return False

    def check_glue_permissions(self):
        """Check AWS Glue permissions"""
        print("3️⃣  Checking Glue Permissions (for database/table)...")
        print("-" * 70)

        glue = boto3.client('glue', region_name=self.region)
        test_db = 'pcp_test_permissions_check'

        # Test CreateDatabase
        try:
            print("Testing glue:CreateDatabase...")
            glue.create_database(
                DatabaseInput={
                    'Name': test_db,
                    'Description': 'Permission test database (will be deleted)'
                }
            )
            print(f"✓ glue:CreateDatabase - ALLOWED")

            # Test GetDatabase
            print("Testing glue:GetDatabase...")
            glue.get_database(Name=test_db)
            print(f"✓ glue:GetDatabase - ALLOWED")

            # Cleanup
            glue.delete_database(Name=test_db)
            print(f"✓ Test database cleaned up")
            print()

            self.tests_passed += 1
            self.results.append(("Glue Permissions", True, "All allowed"))
            return True

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error']['Message']

            # Cleanup if database was created
            try:
                glue.delete_database(Name=test_db)
            except:
                pass

            if 'AccessDenied' in error_code or 'NotAuthorized' in error_msg:
                print(f"✗ FAILED: Access Denied")
                print(f"  Error: {error_msg}")
                print()
                self.tests_failed += 1
                self.results.append(("Glue Permissions", False, "Access Denied"))
                return False
            else:
                print(f"⚠️  Warning: {error_msg}")
                print()
                self.tests_failed += 1
                self.results.append(("Glue Permissions", False, error_code))
                return False

    def check_s3_permissions(self):
        """Check S3 permissions for Athena query results"""
        print("4️⃣  Checking S3 Permissions (for query results)...")
        print("-" * 70)

        s3 = boto3.client('s3', region_name=self.region)
        test_key = 'athena-test/permission-check.txt'

        try:
            # Test PutObject
            print(f"Testing s3:PutObject on {self.bucket}...")
            s3.put_object(
                Bucket=self.bucket,
                Key=test_key,
                Body=b'permission test'
            )
            print(f"✓ s3:PutObject - ALLOWED")

            # Test GetObject
            print(f"Testing s3:GetObject...")
            s3.get_object(Bucket=self.bucket, Key=test_key)
            print(f"✓ s3:GetObject - ALLOWED")

            # Test ListBucket
            print(f"Testing s3:ListBucket...")
            s3.list_objects_v2(Bucket=self.bucket, Prefix='athena-test/', MaxKeys=1)
            print(f"✓ s3:ListBucket - ALLOWED")

            # Cleanup
            s3.delete_object(Bucket=self.bucket, Key=test_key)
            print(f"✓ Test file cleaned up")
            print()

            self.tests_passed += 1
            self.results.append(("S3 Permissions", True, "All allowed"))
            return True

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error']['Message']

            # Cleanup if file was created
            try:
                s3.delete_object(Bucket=self.bucket, Key=test_key)
            except:
                pass

            print(f"✗ FAILED: {error_msg}")
            print()
            self.tests_failed += 1
            self.results.append(("S3 Permissions", False, error_code))
            return False

    def print_summary(self):
        """Print test summary and recommendations"""
        print()
        print("=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print()

        total = self.tests_passed + self.tests_failed

        for i, (test_name, passed, message) in enumerate(self.results, 1):
            status = "✓ PASSED" if passed else "✗ FAILED"
            print(f"{i}. {test_name}: {status}")
            if not passed:
                print(f"   Reason: {message}")

        print()
        print(f"Total Tests: {total}")
        print(f"Passed:      {self.tests_passed} ✓")
        print(f"Failed:      {self.tests_failed} ✗")
        print()

        if self.tests_failed > 0:
            print("=" * 70)
            print("REQUIRED IAM POLICY")
            print("=" * 70)
            print()
            print("Add this IAM policy to your AWS user:")
            print()
            print("""```json
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
        "glue:GetPartitions"
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
        "s3:PutObject"
      ],
      "Resource": [
        "arn:aws:s3:::""" + self.bucket + """",
        "arn:aws:s3:::""" + self.bucket + """/*"
      ]
    }
  ]
}
```""")
            print()
            print("=" * 70)
            print("HOW TO ADD IAM POLICY")
            print("=" * 70)
            print()
            print("Method 1: AWS Console")
            print("-" * 70)
            print("1. Go to AWS IAM Console: https://console.aws.amazon.com/iam/")
            print("2. Click 'Users' → Select your user (pcp-data)")
            print("3. Click 'Add permissions' → 'Create inline policy'")
            print("4. Click 'JSON' tab")
            print("5. Paste the policy above")
            print("6. Click 'Review policy'")
            print("7. Name: 'AthenaQueryPolicy'")
            print("8. Click 'Create policy'")
            print()
            print("Method 2: AWS CLI")
            print("-" * 70)
            print("1. Save the policy above to 'athena-policy.json'")
            print("2. Run:")
            print()
            print("   aws iam put-user-policy \\")
            print("     --user-name pcp-data \\")
            print("     --policy-name AthenaQueryPolicy \\")
            print("     --policy-document file://athena-policy.json")
            print()
        else:
            print("🎉 ALL PERMISSIONS ARE CONFIGURED CORRECTLY!")
            print()
            print("You can now use AWS Athena to query PCP metrics:")
            print()
            print("  python3 query_athena.py --setup-only")
            print("  python3 query_athena.py")
            print()

        print("=" * 70)

        return self.tests_failed == 0

    def run_all_checks(self):
        """Run all permission checks"""
        self.print_header()

        # Run checks
        if not self.check_credentials():
            print("\n⚠️  Cannot proceed without valid AWS credentials")
            print("Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env file")
            return False

        self.check_athena_permissions()
        self.check_glue_permissions()
        self.check_s3_permissions()

        # Print summary
        return self.print_summary()


class AthenaQueryExecutor:
    """Execute AWS Athena queries on PCP metrics data"""

    def __init__(self, region=AWS_REGION):
        """Initialize Athena client and configuration"""
        self.region = region
        self.athena_client = boto3.client('athena', region_name=region)
        self.s3_client = boto3.client('s3', region_name=region)
        self.glue_client = boto3.client('glue', region_name=region)

        self.database = ATHENA_DATABASE
        self.table = ATHENA_TABLE
        self.bucket = S3_BUCKET_NAME
        self.key_prefix = S3_KEY_PREFIX
        self.output_location = ATHENA_OUTPUT_LOCATION

    def delete_database_if_exists(self):
        """Delete database if it exists (Step 1)"""
        print(f"🗑️  Checking if database '{self.database}' exists...")

        try:
            # Check if database exists
            self.glue_client.get_database(Name=self.database)
            print(f"⚠️  Database '{self.database}' exists, deleting...")

            # Delete database (cascade deletes tables)
            query = f"DROP DATABASE IF EXISTS {self.database} CASCADE"
            query_id = self._execute_query(query)
            self._wait_for_query(query_id)
            print(f"✓ Database '{self.database}' deleted")
            return True
        except self.glue_client.exceptions.EntityNotFoundException:
            print(f"✓ Database '{self.database}' does not exist (OK)")
            return True
        except Exception as e:
            print(f"⚠️  Warning during database check: {e}")
            return True

    def create_database(self):
        """Create Athena database (Step 1)"""
        print(f"📁 Creating database: {self.database}")

        query = f"""
        CREATE DATABASE IF NOT EXISTS {self.database}
        COMMENT 'FST PCP Metrics Database'
        LOCATION '{S3_DATA_LOCATION}'
        """

        try:
            query_id = self._execute_query(query)
            self._wait_for_query(query_id)
            print(f"✓ Database '{self.database}' ready")
            return True
        except Exception as e:
            print(f"✗ Failed to create database: {e}")
            return False

    def delete_table_if_exists(self):
        """Delete table if it exists (Step 2)"""
        print(f"🗑️  Checking if table '{self.table}' exists...")

        try:
            # Check if table exists
            self.glue_client.get_table(DatabaseName=self.database, Name=self.table)
            print(f"⚠️  Table '{self.table}' exists, deleting...")

            # Delete table
            query = f"DROP TABLE IF EXISTS {self.database}.{self.table}"
            query_id = self._execute_query(query)
            self._wait_for_query(query_id)
            print(f"✓ Table '{self.table}' deleted")
            return True
        except self.glue_client.exceptions.EntityNotFoundException:
            print(f"✓ Table '{self.table}' does not exist (OK)")
            return True
        except Exception as e:
            print(f"⚠️  Warning during table check: {e}")
            return True

    def create_table(self):
        """Create Athena table for PCP metrics (Step 2)"""
        print(f"📊 Creating table: {self.table}")

        # Use the full schema with all 395+ columns
        query = f"""
        CREATE EXTERNAL TABLE IF NOT EXISTS {self.database}.{self.table} (
            `timestamp` bigint,
            `hinv.ncpu` double,
            `hinv.physmem` double,
            `hinv.pagesize` double,
            `hinv.ndisk` double,
            `hinv.cpu.model_name-cpu0` string,
            `hinv.cpu.model_name-cpu1` string,
            `hinv.cpu.model_name-cpu2` string,
            `hinv.cpu.model_name-cpu3` string,
            `hinv.cpu.model_name-cpu4` string,
            `hinv.cpu.model_name-cpu5` string,
            `hinv.cpu.model_name-cpu6` string,
            `hinv.cpu.model_name-cpu7` string,
            `hinv.cpu.clock-cpu0` double,
            `hinv.cpu.clock-cpu1` double,
            `hinv.cpu.clock-cpu2` double,
            `hinv.cpu.clock-cpu3` double,
            `hinv.cpu.clock-cpu4` double,
            `hinv.cpu.clock-cpu5` double,
            `hinv.cpu.clock-cpu6` double,
            `hinv.cpu.clock-cpu7` double,
            `kernel.uname.release` string,
            `kernel.uname.nodename` string,
            `kernel.uname.distro` string,
            `kernel.all.uptime` double,
            `kernel.all.cpu.user` double,
            `kernel.all.cpu.sys` double,
            `kernel.all.cpu.idle` double,
            `kernel.all.cpu.wait.total` double,
            `kernel.all.cpu.steal` double,
            `kernel.all.cpu.irq.soft` double,
            `kernel.all.cpu.irq.hard` double,
            `kernel.all.load-1 minute` double,
            `kernel.all.load-5 minute` double,
            `kernel.all.load-15 minute` double,
            `kernel.all.running` double,
            `kernel.all.blocked` double,
            `kernel.all.pswitch` double,
            `kernel.all.intr` double,
            `kernel.cpu.util.user` double,
            `kernel.cpu.util.sys` double,
            `kernel.cpu.util.idle` double,
            `mem.physmem` double,
            `mem.freemem` double,
            `mem.util.used` double,
            `mem.util.free` double,
            `mem.util.cached` double,
            `mem.util.bufmem` double,
            `mem.util.active` double,
            `mem.util.inactive` double,
            `mem.util.swaptotal` double,
            `mem.util.swapfree` double,
            `mem.util.swapcached` double,
            `mem.util.dirty` double,
            `mem.util.slab` double,
            `mem.util.available` double,
            `mem.vmstat.pgpgin` double,
            `mem.vmstat.pgpgout` double,
            `mem.vmstat.pswpin` double,
            `mem.vmstat.pswpout` double,
            `mem.vmstat.pgfault` double,
            `mem.vmstat.pgmajfault` double,
            `disk.all.read` double,
            `disk.all.write` double,
            `disk.all.total` double,
            `disk.all.read_bytes` double,
            `disk.all.write_bytes` double,
            `disk.all.total_bytes` double,
            `disk.dev.read-sda` double,
            `disk.dev.read-sdb` double,
            `disk.dev.write-sda` double,
            `disk.dev.write-sdb` double,
            `disk.dev.read_bytes-sda` double,
            `disk.dev.read_bytes-sdb` double,
            `disk.dev.write_bytes-sda` double,
            `disk.dev.write_bytes-sdb` double,
            `disk.dev.avactive-sda` double,
            `disk.dev.avactive-sdb` double,
            `disk.dev.await-sda` double,
            `disk.dev.await-sdb` double,
            `disk.dev.util-sda` double,
            `disk.dev.util-sdb` double,
            `disk.dev.avg_qlen-sda` double,
            `disk.dev.avg_qlen-sdb` double,
            `disk.dev.avg_rqsz-sda` double,
            `disk.dev.avg_rqsz-sdb` double,
            `filesys.capacity-/dev/root` double,
            `filesys.capacity-/dev/sda1` double,
            `filesys.capacity-/dev/mapper/vg_jaguar-var` double,
            `filesys.capacity-/dev/mapper/vg_jaguar-log` double,
            `filesys.capacity-/dev/mapper/vg_jaguar-den.vision` double,
            `filesys.full-/dev/root` double,
            `filesys.full-/dev/sda1` double,
            `filesys.full-/dev/mapper/vg_jaguar-var` double,
            `filesys.full-/dev/mapper/vg_jaguar-log` double,
            `filesys.full-/dev/mapper/vg_jaguar-den.vision` double,
            `vfs.files.count` double,
            `network.interface.in.bytes-lo` double,
            `network.interface.in.bytes-eth0` double,
            `network.interface.in.bytes-vlan100` double,
            `network.interface.in.bytes-int-maint` double,
            `network.interface.in.bytes-vlan-bear-gogo` double,
            `network.interface.in.bytes-bear-gogo` double,
            `network.interface.in.bytes-wlan0` double,
            `network.interface.in.bytes-wlan1` double,
            `network.interface.in.bytes-vlan102` double,
            `network.interface.in.bytes-vlan103` double,
            `network.interface.in.bytes-int-cabin` double,
            `network.interface.in.bytes-int-reserved` double,
            `network.interface.in.bytes-vlan104` double,
            `network.interface.in.bytes-vlan110` double,
            `network.interface.in.bytes-tunl0` double,
            `network.interface.in.bytes-e_portal-eth0` double,
            `network.interface.in.bytes-maint-eth0` double,
            `network.interface.in.bytes-pbx-eth0` double,
            `network.interface.in.bytes-vision-eth0` double,
            `network.interface.in.bytes-isionapi-eth0` double,
            `network.interface.in.bytes-fp3d-eth0` double,
            `network.interface.in.bytes-visiondl-eth0` double,
            `network.interface.in.bytes-drm-eth0` double,
            `network.interface.in.bytes-gamp-eth0` double,
            `network.interface.in.bytes-gamp-eth1` double,
            `network.interface.in.bytes-gamp-eth2` double,
            `network.interface.in.bytes-isionrss-eth0` double,
            `network.interface.out.bytes-lo` double,
            `network.interface.out.bytes-eth0` double,
            `network.interface.out.bytes-vlan100` double,
            `network.interface.out.bytes-int-maint` double,
            `network.interface.out.bytes-vlan-bear-gogo` double,
            `network.interface.out.bytes-bear-gogo` double,
            `network.interface.out.bytes-wlan0` double,
            `network.interface.out.bytes-wlan1` double,
            `network.interface.out.bytes-vlan102` double,
            `network.interface.out.bytes-vlan103` double,
            `network.interface.out.bytes-int-cabin` double,
            `network.interface.out.bytes-int-reserved` double,
            `network.interface.out.bytes-vlan104` double,
            `network.interface.out.bytes-vlan110` double,
            `network.interface.out.bytes-tunl0` double,
            `network.interface.out.bytes-e_portal-eth0` double,
            `network.interface.out.bytes-maint-eth0` double,
            `network.interface.out.bytes-pbx-eth0` double,
            `network.interface.out.bytes-vision-eth0` double,
            `network.interface.out.bytes-isionapi-eth0` double,
            `network.interface.out.bytes-fp3d-eth0` double,
            `network.interface.out.bytes-visiondl-eth0` double,
            `network.interface.out.bytes-drm-eth0` double,
            `network.interface.out.bytes-gamp-eth0` double,
            `network.interface.out.bytes-gamp-eth1` double,
            `network.interface.out.bytes-gamp-eth2` double,
            `network.interface.out.bytes-isionrss-eth0` double,
            `network.interface.total.bytes-lo` double,
            `network.interface.total.bytes-eth0` double,
            `network.interface.total.bytes-vlan100` double,
            `network.interface.total.bytes-int-maint` double,
            `network.interface.total.bytes-vlan-bear-gogo` double,
            `network.interface.total.bytes-bear-gogo` double,
            `network.interface.total.bytes-wlan0` double,
            `network.interface.total.bytes-wlan1` double,
            `network.interface.total.bytes-vlan102` double,
            `network.interface.total.bytes-vlan103` double,
            `network.interface.total.bytes-int-cabin` double,
            `network.interface.total.bytes-int-reserved` double,
            `network.interface.total.bytes-vlan104` double,
            `network.interface.total.bytes-vlan110` double,
            `network.interface.total.bytes-tunl0` double,
            `network.interface.total.bytes-e_portal-eth0` double,
            `network.interface.total.bytes-maint-eth0` double,
            `network.interface.total.bytes-pbx-eth0` double,
            `network.interface.total.bytes-vision-eth0` double,
            `network.interface.total.bytes-isionapi-eth0` double,
            `network.interface.total.bytes-fp3d-eth0` double,
            `network.interface.total.bytes-visiondl-eth0` double,
            `network.interface.total.bytes-drm-eth0` double,
            `network.interface.total.bytes-gamp-eth0` double,
            `network.interface.total.bytes-gamp-eth1` double,
            `network.interface.total.bytes-gamp-eth2` double,
            `network.interface.total.bytes-isionrss-eth0` double,
            `network.interface.in.packets-lo` double,
            `network.interface.in.packets-eth0` double,
            `network.interface.in.packets-vlan100` double,
            `network.interface.in.packets-int-maint` double,
            `network.interface.in.packets-vlan-bear-gogo` double,
            `network.interface.in.packets-bear-gogo` double,
            `network.interface.in.packets-wlan0` double,
            `network.interface.in.packets-wlan1` double,
            `network.interface.in.packets-vlan102` double,
            `network.interface.in.packets-vlan103` double,
            `network.interface.in.packets-int-cabin` double,
            `network.interface.in.packets-int-reserved` double,
            `network.interface.in.packets-vlan104` double,
            `network.interface.in.packets-vlan110` double,
            `network.interface.in.packets-tunl0` double,
            `network.interface.in.packets-e_portal-eth0` double,
            `network.interface.in.packets-maint-eth0` double,
            `network.interface.in.packets-pbx-eth0` double,
            `network.interface.in.packets-vision-eth0` double,
            `network.interface.in.packets-isionapi-eth0` double,
            `network.interface.in.packets-fp3d-eth0` double,
            `network.interface.in.packets-visiondl-eth0` double,
            `network.interface.in.packets-drm-eth0` double,
            `network.interface.in.packets-gamp-eth0` double,
            `network.interface.in.packets-gamp-eth1` double,
            `network.interface.in.packets-gamp-eth2` double,
            `network.interface.in.packets-isionrss-eth0` double,
            `network.interface.out.packets-lo` double,
            `network.interface.out.packets-eth0` double,
            `network.interface.out.packets-vlan100` double,
            `network.interface.out.packets-int-maint` double,
            `network.interface.out.packets-vlan-bear-gogo` double,
            `network.interface.out.packets-bear-gogo` double,
            `network.interface.out.packets-wlan0` double,
            `network.interface.out.packets-wlan1` double,
            `network.interface.out.packets-vlan102` double,
            `network.interface.out.packets-vlan103` double,
            `network.interface.out.packets-int-cabin` double,
            `network.interface.out.packets-int-reserved` double,
            `network.interface.out.packets-vlan104` double,
            `network.interface.out.packets-vlan110` double,
            `network.interface.out.packets-tunl0` double,
            `network.interface.out.packets-e_portal-eth0` double,
            `network.interface.out.packets-maint-eth0` double,
            `network.interface.out.packets-pbx-eth0` double,
            `network.interface.out.packets-vision-eth0` double,
            `network.interface.out.packets-isionapi-eth0` double,
            `network.interface.out.packets-fp3d-eth0` double,
            `network.interface.out.packets-visiondl-eth0` double,
            `network.interface.out.packets-drm-eth0` double,
            `network.interface.out.packets-gamp-eth0` double,
            `network.interface.out.packets-gamp-eth1` double,
            `network.interface.out.packets-gamp-eth2` double,
            `network.interface.out.packets-isionrss-eth0` double,
            `network.interface.in.errors-lo` double,
            `network.interface.in.errors-eth0` double,
            `network.interface.in.errors-vlan100` double,
            `network.interface.in.errors-int-maint` double,
            `network.interface.in.errors-vlan-bear-gogo` double,
            `network.interface.in.errors-bear-gogo` double,
            `network.interface.in.errors-wlan0` double,
            `network.interface.in.errors-wlan1` double,
            `network.interface.in.errors-vlan102` double,
            `network.interface.in.errors-vlan103` double,
            `network.interface.in.errors-int-cabin` double,
            `network.interface.in.errors-int-reserved` double,
            `network.interface.in.errors-vlan104` double,
            `network.interface.in.errors-vlan110` double,
            `network.interface.in.errors-tunl0` double,
            `network.interface.in.errors-e_portal-eth0` double,
            `network.interface.in.errors-maint-eth0` double,
            `network.interface.in.errors-pbx-eth0` double,
            `network.interface.in.errors-vision-eth0` double,
            `network.interface.in.errors-isionapi-eth0` double,
            `network.interface.in.errors-fp3d-eth0` double,
            `network.interface.in.errors-visiondl-eth0` double,
            `network.interface.in.errors-drm-eth0` double,
            `network.interface.in.errors-gamp-eth0` double,
            `network.interface.in.errors-gamp-eth1` double,
            `network.interface.in.errors-gamp-eth2` double,
            `network.interface.in.errors-isionrss-eth0` double,
            `network.interface.out.errors-lo` double,
            `network.interface.out.errors-eth0` double,
            `network.interface.out.errors-vlan100` double,
            `network.interface.out.errors-int-maint` double,
            `network.interface.out.errors-vlan-bear-gogo` double,
            `network.interface.out.errors-bear-gogo` double,
            `network.interface.out.errors-wlan0` double,
            `network.interface.out.errors-wlan1` double,
            `network.interface.out.errors-vlan102` double,
            `network.interface.out.errors-vlan103` double,
            `network.interface.out.errors-int-cabin` double,
            `network.interface.out.errors-int-reserved` double,
            `network.interface.out.errors-vlan104` double,
            `network.interface.out.errors-vlan110` double,
            `network.interface.out.errors-tunl0` double,
            `network.interface.out.errors-e_portal-eth0` double,
            `network.interface.out.errors-maint-eth0` double,
            `network.interface.out.errors-pbx-eth0` double,
            `network.interface.out.errors-vision-eth0` double,
            `network.interface.out.errors-isionapi-eth0` double,
            `network.interface.out.errors-fp3d-eth0` double,
            `network.interface.out.errors-visiondl-eth0` double,
            `network.interface.out.errors-drm-eth0` double,
            `network.interface.out.errors-gamp-eth0` double,
            `network.interface.out.errors-gamp-eth1` double,
            `network.interface.out.errors-gamp-eth2` double,
            `network.interface.out.errors-isionrss-eth0` double,
            `network.interface.in.drops-lo` double,
            `network.interface.in.drops-eth0` double,
            `network.interface.in.drops-vlan100` double,
            `network.interface.in.drops-int-maint` double,
            `network.interface.in.drops-vlan-bear-gogo` double,
            `network.interface.in.drops-bear-gogo` double,
            `network.interface.in.drops-wlan0` double,
            `network.interface.in.drops-wlan1` double,
            `network.interface.in.drops-vlan102` double,
            `network.interface.in.drops-vlan103` double,
            `network.interface.in.drops-int-cabin` double,
            `network.interface.in.drops-int-reserved` double,
            `network.interface.in.drops-vlan104` double,
            `network.interface.in.drops-vlan110` double,
            `network.interface.in.drops-tunl0` double,
            `network.interface.in.drops-e_portal-eth0` double,
            `network.interface.in.drops-maint-eth0` double,
            `network.interface.in.drops-pbx-eth0` double,
            `network.interface.in.drops-vision-eth0` double,
            `network.interface.in.drops-isionapi-eth0` double,
            `network.interface.in.drops-fp3d-eth0` double,
            `network.interface.in.drops-visiondl-eth0` double,
            `network.interface.in.drops-drm-eth0` double,
            `network.interface.in.drops-gamp-eth0` double,
            `network.interface.in.drops-gamp-eth1` double,
            `network.interface.in.drops-gamp-eth2` double,
            `network.interface.in.drops-isionrss-eth0` double,
            `network.interface.out.drops-lo` double,
            `network.interface.out.drops-eth0` double,
            `network.interface.out.drops-vlan100` double,
            `network.interface.out.drops-int-maint` double,
            `network.interface.out.drops-vlan-bear-gogo` double,
            `network.interface.out.drops-bear-gogo` double,
            `network.interface.out.drops-wlan0` double,
            `network.interface.out.drops-wlan1` double,
            `network.interface.out.drops-vlan102` double,
            `network.interface.out.drops-vlan103` double,
            `network.interface.out.drops-int-cabin` double,
            `network.interface.out.drops-int-reserved` double,
            `network.interface.out.drops-vlan104` double,
            `network.interface.out.drops-vlan110` double,
            `network.interface.out.drops-tunl0` double,
            `network.interface.out.drops-e_portal-eth0` double,
            `network.interface.out.drops-maint-eth0` double,
            `network.interface.out.drops-pbx-eth0` double,
            `network.interface.out.drops-vision-eth0` double,
            `network.interface.out.drops-isionapi-eth0` double,
            `network.interface.out.drops-fp3d-eth0` double,
            `network.interface.out.drops-visiondl-eth0` double,
            `network.interface.out.drops-drm-eth0` double,
            `network.interface.out.drops-gamp-eth0` double,
            `network.interface.out.drops-gamp-eth1` double,
            `network.interface.out.drops-gamp-eth2` double,
            `network.interface.out.drops-isionrss-eth0` double,
            `network.interface.up-lo` double,
            `network.interface.up-eth0` double,
            `network.interface.up-vlan100` double,
            `network.interface.up-int-maint` double,
            `network.interface.up-vlan-bear-gogo` double,
            `network.interface.up-bear-gogo` double,
            `network.interface.up-wlan0` double,
            `network.interface.up-wlan1` double,
            `network.interface.up-vlan102` double,
            `network.interface.up-vlan103` double,
            `network.interface.up-int-cabin` double,
            `network.interface.up-int-reserved` double,
            `network.interface.up-vlan104` double,
            `network.interface.up-vlan110` double,
            `network.interface.up-tunl0` double,
            `network.interface.up-e_portal-eth0` double,
            `network.interface.up-maint-eth0` double,
            `network.interface.up-pbx-eth0` double,
            `network.interface.up-vision-eth0` double,
            `network.interface.up-isionapi-eth0` double,
            `network.interface.up-fp3d-eth0` double,
            `network.interface.up-visiondl-eth0` double,
            `network.interface.up-drm-eth0` double,
            `network.interface.up-gamp-eth0` double,
            `network.interface.up-gamp-eth1` double,
            `network.interface.up-gamp-eth2` double,
            `network.interface.up-isionrss-eth0` double,
            `network.tcp.activeopens` double,
            `network.tcp.currestab` double,
            `network.tcp.insegs` double,
            `network.tcp.outsegs` double,
            `network.tcp.retranssegs` double,
            `network.udp.indatagrams` double,
            `network.udp.outdatagrams` double,
            `network.ip.inreceives` double,
            `network.softnet.dropped` double,
            `kernel.all.nprocs` double,
            `kernel.all.sysfork` double,
            `kernel.all.lastpid` double,
            `kernel.all.runnable` double,
            `kernel.all.nusers` double,
            `vfs.inodes.free` double,
            `vfs.dentry.count` double,
            `ipc.shm.tot` double,
            `psoc.now.temp.psoc` double,
            `psoc.now.temp.sensor1` double,
            `psoc.now.vltg.12vbus` double,
            `psoc.now.cur.12vbus` double,
            `psoc.now.fan.rpm` double,
            `psoc.now.status.power_led` double,
            `psoc.past.status.powergoodhrs` double,
            `__index_level_0__` bigint
        )
        PARTITIONED BY (
            `product_type` string,
            `serial_number` string,
            `year` string,
            `month` string,
            `day` string,
            `hour` string
        )
        STORED AS PARQUET
        LOCATION '{S3_DATA_LOCATION}'
        TBLPROPERTIES (
            'parquet.compression'='SNAPPY'
        )
        """

        try:
            query_id = self._execute_query(query)
            self._wait_for_query(query_id)
            print(f"✓ Table '{self.table}' ready")
            return True
        except Exception as e:
            print(f"✗ Failed to create table: {e}")
            return False

    def repair_partitions(self):
        """Discover and add all partitions from S3 (Step 3)"""
        print(f"🔧 Discovering partitions...")

        query = f"""
        MSCK REPAIR TABLE {self.database}.{self.table}
        """

        try:
            query_id = self._execute_query(query)
            result = self._wait_for_query(query_id)
            print(f"✓ Partitions discovered and loaded")
            return True
        except Exception as e:
            print(f"⚠️  Warning: Partition repair failed: {e}")
            print("   (This is normal if no data has been uploaded yet)")
            return False

    def show_partitions(self):
        """Show all partitions in the table (Step 4)"""
        print(f"📋 Showing partitions...")

        query = f"""
        SHOW PARTITIONS {self.database}.{self.table}
        """

        try:
            query_id = self._execute_query(query)
            result = self._wait_for_query(query_id)

            # Get partition results
            df = self._get_query_results(query_id)
            if len(df) > 0:
                print(f"✓ Found {len(df)} partitions:")
                print(df.to_string())
            else:
                print(f"⚠️  No partitions found")
            return True
        except Exception as e:
            print(f"⚠️  Warning: Show partitions failed: {e}")
            return False

    def run_sample_query(self, limit=5):
        """Run sample query to check data (Step 5)"""
        print(f"\n🔍 Running sample query...")

        query = f"""
        SELECT *
        FROM {self.database}.{self.table}
        LIMIT {limit}
        """

        try:
            query_id = self._execute_query(query)
            print(f"Query ID: {query_id}")
            result = self._wait_for_query(query_id)

            if result['QueryExecution']['Status']['State'] == 'SUCCEEDED':
                df = self._get_query_results(query_id)
                print(f"✓ Sample query completed: {len(df)} rows returned")
                if len(df) > 0:
                    print("\nSample Data Preview:")
                    print("-" * 70)
                    print(df.head().to_string())
                return df
            else:
                print(f"✗ Sample query failed")
                return None
        except Exception as e:
            print(f"⚠️  Warning: Sample query failed: {e}")
            return None

    def run_specific_metrics_query(self):
        """Run specific metrics query with partition filters (Step 6)"""
        print(f"\n🔍 Running specific metrics query...")

        # Define specific metrics to query
        metrics = [
            '"kernel.all.load-1 minute"',
            '"kernel.all.load-5 minute"',
            '"kernel.all.load-15 minute"'
        ]

        # Query for data between specific partition ranges
        query = f"""
        SELECT {', '.join(metrics)}
        FROM {self.database}.{self.table}
        WHERE product_type = 'DEV_SW_05'
          AND serial_number = '1234'
          AND year = '2025'
          AND month = '11'
          AND day = '01'
          AND hour >= '15'
          AND hour <= '23'
        LIMIT 10
        """

        try:
            query_id = self._execute_query(query)
            print(f"Query ID: {query_id}")
            print(f"\nQuerying load metrics:")
            print(f"  Product: DEV_SW_05")
            print(f"  Serial: 1234")
            print(f"  Date: 2025-11-01")
            print(f"  Time range: hour 15 to 23")
            print()

            result = self._wait_for_query(query_id)

            if result['QueryExecution']['Status']['State'] == 'SUCCEEDED':
                df = self._get_query_results(query_id)
                print(f"✓ Specific metrics query completed: {len(df)} rows returned")
                if len(df) > 0:
                    print("\nLoad Metrics Results:")
                    print("-" * 70)
                    print(df.to_string())
                else:
                    print("⚠️  No data found for specified filters")
                return df
            else:
                print(f"✗ Specific metrics query failed")
                return None
        except Exception as e:
            print(f"⚠️  Warning: Specific metrics query failed: {e}")
            return None

    def query_metrics(self, start_time, end_time, product_type=None, serial_number=None,
                     metrics=None, limit=1000):
        """
        Query PCP metrics with filters

        Args:
            start_time (str): Start timestamp (YYYY-MM-DD HH:MM:SS)
            end_time (str): End timestamp (YYYY-MM-DD HH:MM:SS)
            product_type (str): Product type filter (optional)
            serial_number (str): Serial number filter (optional)
            metrics (list): List of metric columns to return (optional)
            limit (int): Maximum rows to return

        Returns:
            pandas.DataFrame: Query results
        """
        print(f"\n🔍 Querying metrics...")
        print(f"   Time range: {start_time} to {end_time}")
        if product_type:
            print(f"   Product: {product_type}")
        if serial_number:
            print(f"   Serial: {serial_number}")
        print()

        # Default to all metrics if not specified
        if metrics is None:
            metrics = METRICS_TO_QUERY

        # Build SELECT clause
        select_clause = ', '.join(metrics)

        # Build WHERE clause
        where_conditions = [
            f"timestamp BETWEEN TIMESTAMP '{start_time}' AND TIMESTAMP '{end_time}'"
        ]

        if product_type:
            where_conditions.append(f"product_type = '{product_type}'")

        if serial_number:
            where_conditions.append(f"serial_number = '{serial_number}'")

        where_clause = ' AND '.join(where_conditions)

        # Build complete query
        query = f"""
        SELECT {select_clause}
        FROM {self.database}.{self.table}
        WHERE {where_clause}
        ORDER BY timestamp DESC
        LIMIT {limit}
        """

        print("SQL Query:")
        print("-" * 70)
        print(query)
        print("-" * 70)
        print()

        try:
            # Execute query
            query_id = self._execute_query(query)
            print(f"Query ID: {query_id}")

            # Wait for completion
            result = self._wait_for_query(query_id)

            if result['QueryExecution']['Status']['State'] == 'SUCCEEDED':
                # Get results
                df = self._get_query_results(query_id)
                print(f"✓ Query completed: {len(df)} rows returned")
                return df
            else:
                print(f"✗ Query failed: {result['QueryExecution']['Status'].get('StateChangeReason', 'Unknown error')}")
                return None

        except Exception as e:
            print(f"✗ Query error: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _execute_query(self, query):
        """Execute an Athena query"""
        response = self.athena_client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={'Database': self.database},
            ResultConfiguration={
                'OutputLocation': self.output_location,
                'EncryptionConfiguration': {
                    'EncryptionOption': 'SSE_S3'
                }
            }
        )
        return response['QueryExecutionId']

    def _wait_for_query(self, query_id, max_wait=300):
        """Wait for query to complete"""
        start_time = time.time()

        while True:
            response = self.athena_client.get_query_execution(
                QueryExecutionId=query_id
            )

            state = response['QueryExecution']['Status']['State']

            if state == 'SUCCEEDED':
                return response
            elif state in ['FAILED', 'CANCELLED']:
                reason = response['QueryExecution']['Status'].get('StateChangeReason', 'Unknown')
                raise Exception(f"Query {state}: {reason}")

            # Check timeout
            if time.time() - start_time > max_wait:
                raise Exception(f"Query timeout after {max_wait} seconds")

            time.sleep(1)

    def _get_query_results(self, query_id):
        """Get query results as pandas DataFrame"""
        results = []
        next_token = None

        while True:
            if next_token:
                response = self.athena_client.get_query_results(
                    QueryExecutionId=query_id,
                    NextToken=next_token
                )
            else:
                response = self.athena_client.get_query_results(
                    QueryExecutionId=query_id
                )

            # Extract column names from first page
            if not results:
                columns = [col['Label'] for col in response['ResultSet']['ResultSetMetadata']['ColumnInfo']]
                # Skip header row
                rows = response['ResultSet']['Rows'][1:]
            else:
                rows = response['ResultSet']['Rows']

            # Extract data
            for row in rows:
                values = [field.get('VarCharValue', None) for field in row['Data']]
                results.append(values)

            # Check for more pages
            next_token = response.get('NextToken')
            if not next_token:
                break

        # Create DataFrame
        if results:
            df = pd.DataFrame(results, columns=columns)

            # Convert timestamp column (stored as nanoseconds)
            if 'timestamp' in df.columns:
                # Convert from nanoseconds to seconds first to avoid overflow
                df['timestamp'] = pd.to_datetime(df['timestamp'].astype(float) / 1e9, unit='s', errors='coerce')

            # Convert numeric columns
            for col in df.columns:
                if col != 'timestamp':
                    try:
                        df[col] = pd.to_numeric(df[col], errors='ignore')
                    except:
                        pass

            return df
        else:
            return pd.DataFrame()

    def show_summary(self, df):
        """Display summary statistics of query results"""
        if df is None or len(df) == 0:
            print("No data to summarize")
            return

        print("\n" + "=" * 70)
        print("QUERY RESULTS SUMMARY")
        print("=" * 70)
        print(f"Total Rows: {len(df)}")
        print(f"Columns: {len(df.columns)}")
        print()

        # Time range
        if 'timestamp' in df.columns:
            print(f"Time Range:")
            print(f"  First: {df['timestamp'].min()}")
            print(f"  Last:  {df['timestamp'].max()}")
            print()

        # Numeric columns summary
        numeric_cols = df.select_dtypes(include=['number']).columns
        if len(numeric_cols) > 0:
            print("Metric Statistics:")
            print("-" * 70)
            stats = df[numeric_cols].describe()
            print(stats.to_string())
            print()

        # Preview
        print("First 5 Rows:")
        print("-" * 70)
        print(df.head().to_string())
        print()


def main():
    """Main execution function"""
    parser = argparse.ArgumentParser(
        description='Query PCP metrics from AWS Athena',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check IAM permissions
  python3 query_athena.py --check-permissions

  # Query last 7 days (default)
  python3 query_athena.py

  # Query specific time range
  python3 query_athena.py --start-time "2025-11-01 00:00:00" --end-time "2025-11-30 23:59:59"

  # Query specific product
  python3 query_athena.py --product-type "SERVER1" --serial-number "1234"

  # Export to CSV
  python3 query_athena.py --output results.csv

  # Show summary only
  python3 query_athena.py --summary-only
        """
    )

    parser.add_argument('--check-permissions', action='store_true',
                       help='Check AWS IAM permissions and exit')
    parser.add_argument('--start-time', default=DEFAULT_START_TIME,
                       help=f'Start time (default: {DEFAULT_START_TIME})')
    parser.add_argument('--end-time', default=DEFAULT_END_TIME,
                       help=f'End time (default: {DEFAULT_END_TIME})')
    parser.add_argument('--product-type', default=PRODUCT_TYPE,
                       help=f'Product type filter (default: {PRODUCT_TYPE})')
    parser.add_argument('--serial-number', default=SERIAL_NUMBER,
                       help=f'Serial number filter (default: {SERIAL_NUMBER})')
    parser.add_argument('--limit', type=int, default=1000,
                       help='Maximum rows to return (default: 1000)')
    parser.add_argument('--output', help='Output CSV file path (optional)')
    parser.add_argument('--summary-only', action='store_true',
                       help='Show summary statistics only')
    parser.add_argument('--setup-only', action='store_true',
                       help='Setup database and table only, skip query')

    args = parser.parse_args()

    # Handle permission check mode
    if args.check_permissions:
        checker = PermissionChecker()
        all_passed = checker.run_all_checks()
        sys.exit(0 if all_passed else 1)

    print("=" * 70)
    print("AWS Athena Query Tool for PCP Metrics")
    print("=" * 70)
    print()

    # Initialize executor
    executor = AthenaQueryExecutor(region=AWS_REGION)

    # Setup database and table
    print("🚀 Setting up Athena database and table...")
    print()

    # Step 1: Delete and create database
    print("Step 1: Database Setup")
    print("-" * 70)
    executor.delete_database_if_exists()
    if not executor.create_database():
        print("Failed to create database")
        sys.exit(1)
    print()

    # Step 2: Delete and create table
    print("Step 2: Table Setup")
    print("-" * 70)
    executor.delete_table_if_exists()
    if not executor.create_table():
        print("Failed to create table")
        sys.exit(1)
    print()

    # Step 3: Discover partitions
    print("Step 3: Partition Discovery")
    print("-" * 70)
    executor.repair_partitions()
    print()

    # Step 4: Show partitions
    print("Step 4: Show Partitions")
    print("-" * 70)
    executor.show_partitions()
    print()

    if args.setup_only:
        # Step 5: Run sample query
        print("Step 5: Sample Query")
        print("-" * 70)
        executor.run_sample_query(limit=5)
        print()

        # Step 6: Run specific metrics query
        print("Step 6: Specific Metrics Query")
        print("-" * 70)
        executor.run_specific_metrics_query()

        print("\n" + "=" * 70)
        print("✓ Setup complete!")
        print("=" * 70)
        print(f"  Database: {ATHENA_DATABASE}")
        print(f"  Table: {ATHENA_TABLE}")
        print(f"  Location: {S3_DATA_LOCATION}")
        sys.exit(0)

    # Query data
    df = executor.query_metrics(
        start_time=args.start_time,
        end_time=args.end_time,
        product_type=args.product_type,
        serial_number=args.serial_number,
        limit=args.limit
    )

    if df is None:
        print("Query failed")
        sys.exit(1)

    # Show summary
    executor.show_summary(df)

    # Export to CSV if requested
    if args.output and len(df) > 0:
        print(f"\n💾 Exporting to CSV: {args.output}")
        df.to_csv(args.output, index=False)
        print(f"✓ Saved {len(df)} rows to {args.output}")

    # Show full results if not summary-only
    if not args.summary_only and len(df) > 0:
        print("\n" + "=" * 70)
        print("FULL RESULTS")
        print("=" * 70)
        print(df.to_string())

    print("\n✓ Query complete!")


if __name__ == '__main__':
    main()
