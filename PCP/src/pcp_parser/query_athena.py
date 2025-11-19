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
ATHENA_DATABASE = 'pcp_metrics_db'
ATHENA_TABLE = 'pcp_metrics'
ATHENA_OUTPUT_BUCKET = S3_BUCKET_NAME  # Use same bucket for query results
ATHENA_OUTPUT_PREFIX = 'athena-results/'

# Query Filters - CUSTOMIZE THESE
PRODUCT_TYPE = os.getenv('PRODUCT_TYPE', 'SW_DEV_11')
SERIAL_NUMBER = os.getenv('SERIAL_NUMBER', '1235678')

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
        self.output_location = f's3://{ATHENA_OUTPUT_BUCKET}/{ATHENA_OUTPUT_PREFIX}'

    def create_database(self):
        """Create Athena database if it doesn't exist"""
        print(f"📁 Creating database: {self.database}")

        query = f"""
        CREATE DATABASE IF NOT EXISTS {self.database}
        COMMENT 'PCP Metrics Database'
        LOCATION 's3://{self.bucket}/{self.key_prefix}'
        """

        try:
            query_id = self._execute_query(query)
            self._wait_for_query(query_id)
            print(f"✓ Database '{self.database}' ready")
            return True
        except Exception as e:
            print(f"✗ Failed to create database: {e}")
            return False

    def create_table(self):
        """Create Athena table for PCP metrics if it doesn't exist"""
        print(f"📊 Creating table: {self.table}")

        # Construct S3 location
        if self.key_prefix:
            s3_location = f's3://{self.bucket}/{self.key_prefix}'
        else:
            s3_location = f's3://{self.bucket}/'

        query = f"""
        CREATE EXTERNAL TABLE IF NOT EXISTS {self.database}.{self.table} (
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
            year STRING,
            month STRING,
            day STRING,
            hour STRING,
            product_type STRING,
            serial_number STRING
        )
        STORED AS PARQUET
        LOCATION '{s3_location}'
        TBLPROPERTIES ('parquet.compression'='SNAPPY')
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
        """Discover and add all partitions from S3"""
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

            # Convert timestamp column
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])

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

    if not executor.create_database():
        print("Failed to create database")
        sys.exit(1)

    if not executor.create_table():
        print("Failed to create table")
        sys.exit(1)

    # Discover partitions
    executor.repair_partitions()

    if args.setup_only:
        print("\n✓ Setup complete!")
        print(f"  Database: {ATHENA_DATABASE}")
        print(f"  Table: {ATHENA_TABLE}")
        print(f"  Location: s3://{S3_BUCKET_NAME}/{S3_KEY_PREFIX}")
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
