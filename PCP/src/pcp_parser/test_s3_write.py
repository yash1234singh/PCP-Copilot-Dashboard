#!/usr/bin/env python3
"""
AWS S3 Write Test Script for PCP Parquet Export

This script tests the S3 write functionality including:
1. S3 connection and credentials
2. Basic file upload
3. Parquet file creation and upload with partitioning
4. File listing and verification

Usage:
    python3 test_s3_write.py

    Or from Docker:
    docker exec pcp_parser_python python3 /app/test_s3_write.py
"""

import os
import sys
import boto3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from io import BytesIO
from datetime import datetime
from botocore.exceptions import ClientError, NoCredentialsError


class S3WriteTester:
    """Test AWS S3 write functionality for PCP Parquet export"""

    def __init__(self):
        """Initialize S3 tester with environment configuration"""
        self.bucket_name = os.getenv('S3_BUCKET_NAME', 'fst-pcp-data1')
        self.region = os.getenv('AWS_REGION', 'us-west-2')
        self.key_prefix = os.getenv('S3_KEY_PREFIX', '')
        self.product_type = os.getenv('PRODUCT_TYPE', 'TEST')
        self.serial_number = os.getenv('SERIAL_NUMBER', '0000')
        self.compression = os.getenv('PARQUET_COMPRESSION', 'snappy')

        # Test prefix for all test files
        self.test_prefix = 'test/'

        # Results tracking
        self.tests_passed = 0
        self.tests_failed = 0
        self.test_results = []

    def print_config(self):
        """Print current S3 configuration"""
        print("=" * 70)
        print("AWS S3 Write Test - Configuration")
        print("=" * 70)
        print(f"S3 Bucket:       {self.bucket_name}")
        print(f"AWS Region:      {self.region}")
        print(f"Key Prefix:      '{self.key_prefix}' (empty = bucket root)")
        print(f"Product Type:    {self.product_type}")
        print(f"Serial Number:   {self.serial_number}")
        print(f"Compression:     {self.compression}")
        print(f"Test Prefix:     {self.test_prefix}")
        print("=" * 70)
        print()

    def test_1_credentials(self):
        """Test 1: Verify AWS credentials are configured"""
        test_name = "AWS Credentials Check"
        print(f"📋 Test 1: {test_name}")
        print("-" * 70)

        try:
            access_key = os.getenv('AWS_ACCESS_KEY_ID')
            secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')

            if not access_key or not secret_key:
                print("✗ FAILED: AWS credentials not found in environment")
                print("  Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env file")
                self.tests_failed += 1
                self.test_results.append((test_name, False, "Credentials not set"))
                return False

            print(f"✓ AWS_ACCESS_KEY_ID: {access_key[:10]}... (found)")
            print(f"✓ AWS_SECRET_ACCESS_KEY: ****** (found)")
            print(f"✓ PASSED: Credentials are configured")
            print()

            self.tests_passed += 1
            self.test_results.append((test_name, True, "Credentials found"))
            return True

        except Exception as e:
            print(f"✗ FAILED: {e}")
            print()
            self.tests_failed += 1
            self.test_results.append((test_name, False, str(e)))
            return False

    def test_2_connection(self):
        """Test 2: Test S3 connection and bucket access"""
        test_name = "S3 Connection Test"
        print(f"📡 Test 2: {test_name}")
        print("-" * 70)

        try:
            # Create S3 client
            s3_client = boto3.client('s3', region_name=self.region)

            # Try to head the bucket
            s3_client.head_bucket(Bucket=self.bucket_name)

            print(f"✓ Successfully connected to S3")
            print(f"✓ Bucket '{self.bucket_name}' is accessible")
            print(f"✓ Region: {self.region}")
            print(f"✓ PASSED: S3 connection successful")
            print()

            self.tests_passed += 1
            self.test_results.append((test_name, True, "Connection successful"))
            return True

        except NoCredentialsError:
            print("✗ FAILED: No AWS credentials found")
            print("  Check AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY")
            print()
            self.tests_failed += 1
            self.test_results.append((test_name, False, "No credentials"))
            return False

        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                print(f"✗ FAILED: Bucket '{self.bucket_name}' does not exist")
            elif error_code == '403':
                print(f"✗ FAILED: Access denied to bucket '{self.bucket_name}'")
                print("  Check IAM permissions: s3:ListBucket")
            else:
                print(f"✗ FAILED: {e}")
            print()
            self.tests_failed += 1
            self.test_results.append((test_name, False, error_code))
            return False

        except Exception as e:
            print(f"✗ FAILED: {e}")
            print()
            self.tests_failed += 1
            self.test_results.append((test_name, False, str(e)))
            return False

    def test_3_simple_write(self):
        """Test 3: Test simple file upload (PutObject permission)"""
        test_name = "Simple File Upload"
        print(f"📝 Test 3: {test_name}")
        print("-" * 70)

        try:
            s3_client = boto3.client('s3', region_name=self.region)

            # Create test file
            test_key = f"{self.test_prefix}test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            test_content = f"Test file created at {datetime.now().isoformat()}"

            print(f"Uploading test file: {test_key}")

            # Upload
            s3_client.put_object(
                Bucket=self.bucket_name,
                Key=test_key,
                Body=test_content.encode('utf-8')
            )

            print(f"✓ File uploaded successfully")
            print(f"  S3 Path: s3://{self.bucket_name}/{test_key}")
            print(f"  Size: {len(test_content)} bytes")
            print(f"✓ PASSED: Simple write successful")
            print()

            self.tests_passed += 1
            self.test_results.append((test_name, True, "Upload successful"))
            return True

        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'AccessDenied':
                print(f"✗ FAILED: Access denied")
                print("  Missing IAM permission: s3:PutObject")
                print(f"  Resource: arn:aws:s3:::{self.bucket_name}/*")
            else:
                print(f"✗ FAILED: {e}")
            print()
            self.tests_failed += 1
            self.test_results.append((test_name, False, error_code))
            return False

        except Exception as e:
            print(f"✗ FAILED: {e}")
            print()
            self.tests_failed += 1
            self.test_results.append((test_name, False, str(e)))
            return False

    def test_4_parquet_write(self):
        """Test 4: Test Parquet file creation and upload with partitioning"""
        test_name = "Parquet File Upload"
        print(f"📊 Test 4: {test_name}")
        print("-" * 70)

        try:
            # Create test DataFrame
            print("Creating test Parquet data...")
            now = datetime.now()
            df = pd.DataFrame({
                'timestamp': [now],
                'kernel_all_cpu_idle': [95.5],
                'kernel_all_cpu_user': [3.2],
                'mem_util_used': [2048.0],
                'mem_util_free': [6144.0],
                'disk_dev_read': [1024.5],
                'disk_dev_write': [512.3]
            })

            # Add partition columns
            df['year'] = now.strftime('%Y')
            df['month'] = now.strftime('%m')
            df['day'] = now.strftime('%d')
            df['hour'] = now.strftime('%H')
            df['product_type'] = self.product_type
            df['serial_number'] = self.serial_number

            print(f"✓ Created DataFrame with {len(df)} rows, {len(df.columns)} columns")

            # Convert to Parquet
            print(f"Converting to Parquet format (compression: {self.compression})...")
            buffer = BytesIO()
            table = pa.Table.from_pandas(df)
            pq.write_table(table, buffer, compression=self.compression)
            buffer.seek(0)
            parquet_data = buffer.getvalue()

            print(f"✓ Parquet file created: {len(parquet_data)} bytes")

            # Generate S3 key with Hive-style partitioning
            timestamp = now.strftime('%Y%m%d_%H%M%S')
            s3_key = (
                f"{self.test_prefix}"
                f"year={df['year'].iloc[0]}/"
                f"month={df['month'].iloc[0]}/"
                f"day={df['day'].iloc[0]}/"
                f"hour={df['hour'].iloc[0]}/"
                f"product_type={self.product_type}/"
                f"serial_number={self.serial_number}/"
                f"test_{timestamp}.parquet"
            )

            print(f"Uploading to: {s3_key}")

            # Upload to S3
            s3_client = boto3.client('s3', region_name=self.region)
            s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=parquet_data,
                ContentType='application/octet-stream'
            )

            print(f"✓ Parquet file uploaded successfully")
            print(f"  S3 Path: s3://{self.bucket_name}/{s3_key}")
            print(f"  Format: Parquet ({self.compression} compression)")
            print(f"  Rows: {len(df)}")
            print(f"  Columns: {len(df.columns)}")
            print(f"  Size: {len(parquet_data) / 1024:.2f} KB")
            print(f"✓ PASSED: Parquet upload successful")
            print()

            self.tests_passed += 1
            self.test_results.append((test_name, True, "Parquet upload successful"))
            return True

        except ClientError as e:
            error_code = e.response['Error']['Code']
            print(f"✗ FAILED: {e}")
            print()
            self.tests_failed += 1
            self.test_results.append((test_name, False, error_code))
            return False

        except Exception as e:
            print(f"✗ FAILED: {e}")
            import traceback
            traceback.print_exc()
            print()
            self.tests_failed += 1
            self.test_results.append((test_name, False, str(e)))
            return False

    def test_5_list_files(self):
        """Test 5: List uploaded files to verify"""
        test_name = "List Files Verification"
        print(f"📁 Test 5: {test_name}")
        print("-" * 70)

        try:
            s3_client = boto3.client('s3', region_name=self.region)

            print(f"Listing files in: s3://{self.bucket_name}/{self.test_prefix}")

            response = s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=self.test_prefix,
                MaxKeys=20
            )

            if 'Contents' not in response:
                print("✗ FAILED: No files found in test directory")
                print()
                self.tests_failed += 1
                self.test_results.append((test_name, False, "No files found"))
                return False

            files = response['Contents']
            print(f"✓ Found {len(files)} file(s):\n")

            for obj in files:
                size_kb = obj['Size'] / 1024
                print(f"  📄 {obj['Key']}")
                print(f"     Size: {size_kb:.2f} KB")
                print(f"     Modified: {obj['LastModified']}")
                print()

            print(f"✓ PASSED: File listing successful")
            print()

            self.tests_passed += 1
            self.test_results.append((test_name, True, f"{len(files)} files found"))
            return True

        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'AccessDenied':
                print(f"✗ FAILED: Access denied")
                print("  Missing IAM permission: s3:ListBucket")
            else:
                print(f"✗ FAILED: {e}")
            print()
            self.tests_failed += 1
            self.test_results.append((test_name, False, error_code))
            return False

        except Exception as e:
            print(f"✗ FAILED: {e}")
            print()
            self.tests_failed += 1
            self.test_results.append((test_name, False, str(e)))
            return False

    def print_summary(self):
        """Print test summary"""
        print()
        print("=" * 70)
        print("Test Summary")
        print("=" * 70)

        total_tests = self.tests_passed + self.tests_failed

        for i, (test_name, passed, message) in enumerate(self.test_results, 1):
            status = "✓ PASSED" if passed else "✗ FAILED"
            print(f"{i}. {test_name}: {status} - {message}")

        print()
        print(f"Total Tests: {total_tests}")
        print(f"Passed:      {self.tests_passed} ✓")
        print(f"Failed:      {self.tests_failed} ✗")

        if self.tests_failed == 0:
            print()
            print("🎉 ALL TESTS PASSED! AWS S3 write is fully functional.")
            print()
            print("Next steps:")
            print("  1. Set ENABLE_S3_EXPORT=true in docker-compose.yml")
            print("  2. Process PCP archives - they will automatically export to S3")
            print("  3. Query data with AWS Athena for analytics")
        else:
            print()
            print("⚠️  SOME TESTS FAILED. Check IAM permissions above.")
            print()
            print("Required IAM permissions:")
            print("  - s3:PutObject    (write files)")
            print("  - s3:GetObject    (read files)")
            print("  - s3:ListBucket   (list files)")

        print("=" * 70)

        return self.tests_failed == 0


def main():
    """Run all S3 write tests"""
    tester = S3WriteTester()

    # Print configuration
    tester.print_config()

    # Run tests
    tester.test_1_credentials()
    tester.test_2_connection()
    tester.test_3_simple_write()
    tester.test_4_parquet_write()
    tester.test_5_list_files()

    # Print summary
    all_passed = tester.print_summary()

    # Exit with appropriate code
    sys.exit(0 if all_passed else 1)


if __name__ == '__main__':
    main()
