#!/usr/bin/env python3
"""
AWS S3 Parquet Exporter for PCP Metrics
Exports CSV data to S3 in Parquet format with partitioning by date, time, product_type, and serial_number
"""

import os
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

# AWS S3 Configuration
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "pcp-metrics-parquet")
S3_KEY_PREFIX = os.getenv("S3_KEY_PREFIX", "time-series-data/")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")

# Parquet Configuration
PARQUET_COMPRESSION = os.getenv("PARQUET_COMPRESSION", "snappy")  # Options: snappy, gzip, brotli, lz4, zstd
PARQUET_ROW_GROUP_SIZE = int(os.getenv("PARQUET_ROW_GROUP_SIZE", "100000"))  # Rows per row group

# Feature Flag
ENABLE_S3_EXPORT = os.getenv("ENABLE_S3_EXPORT", "false").lower() == "true"


class S3ParquetExporter:
    """Export PCP metrics CSV data to AWS S3 in Parquet format with partitioning"""

    def __init__(self, product_type: str, serial_number: str, logger: logging.Logger):
        """
        Initialize S3 Parquet Exporter

        Args:
            product_type: Product type identifier (from .env)
            serial_number: Serial number (from .env)
            logger: Logger instance
        """
        self.product_type = product_type
        self.serial_number = serial_number
        self.logger = logger
        self.s3_client = None

        if ENABLE_S3_EXPORT:
            self._initialize_s3_client()

    def _initialize_s3_client(self) -> bool:
        """Initialize AWS S3 client with credentials"""
        try:
            # Initialize boto3 client
            if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
                self.s3_client = boto3.client(
                    's3',
                    region_name=AWS_REGION,
                    aws_access_key_id=AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
                )
                self.logger.info(f"✓ S3 client initialized (region: {AWS_REGION})")
            else:
                # Use default credentials (EC2 role, environment, or ~/.aws/credentials)
                self.s3_client = boto3.client('s3', region_name=AWS_REGION)
                self.logger.info(f"✓ S3 client initialized with default credentials (region: {AWS_REGION})")

            # Test bucket access
            self.s3_client.head_bucket(Bucket=S3_BUCKET_NAME)
            self.logger.info(f"✓ S3 bucket accessible: {S3_BUCKET_NAME}")
            return True

        except NoCredentialsError:
            self.logger.error("✗ AWS credentials not found. Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY")
            return False
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                self.logger.error(f"✗ S3 bucket does not exist: {S3_BUCKET_NAME}")
            elif error_code == '403':
                self.logger.error(f"✗ Access denied to S3 bucket: {S3_BUCKET_NAME}")
            else:
                self.logger.error(f"✗ S3 client initialization failed: {e}")
            return False
        except Exception as e:
            self.logger.error(f"✗ Unexpected error initializing S3 client: {e}")
            return False

    def load_csv_to_dataframe(self, csv_file_path: Path) -> Optional[pd.DataFrame]:
        """
        Load CSV file into pandas DataFrame

        Args:
            csv_file_path: Path to CSV file (e.g., pmrep_output_20251113.csv)

        Returns:
            DataFrame with parsed data, or None if failed
        """
        try:
            if not csv_file_path.exists():
                self.logger.error(f"CSV file not found: {csv_file_path}")
                return None

            self.logger.info(f"Loading CSV file: {csv_file_path}")

            # Read CSV with pandas
            df = pd.read_csv(csv_file_path)

            # Validate that we have data
            if df.empty:
                self.logger.warning(f"CSV file is empty: {csv_file_path}")
                return None

            self.logger.info(f"✓ Loaded CSV: {len(df)} rows, {len(df.columns)} columns")

            return df

        except Exception as e:
            self.logger.error(f"Error loading CSV file: {e}", exc_info=True)
            return None

    def add_partition_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add partition columns to DataFrame for S3 partitioning

        Partition structure: year/month/day/hour/product_type/serial_number/

        Args:
            df: DataFrame with timestamp column

        Returns:
            DataFrame with added partition columns
        """
        try:
            # Ensure first column is parsed as datetime
            timestamp_col = df.columns[0]
            df[timestamp_col] = pd.to_datetime(df[timestamp_col])

            # Extract partition columns from timestamp
            df['year'] = df[timestamp_col].dt.year
            df['month'] = df[timestamp_col].dt.month.astype(str).str.zfill(2)
            df['day'] = df[timestamp_col].dt.day.astype(str).str.zfill(2)
            df['hour'] = df[timestamp_col].dt.hour.astype(str).str.zfill(2)

            # Add product metadata as partition columns
            df['product_type'] = self.product_type
            df['serial_number'] = self.serial_number

            self.logger.info(f"✓ Added partition columns: year, month, day, hour, product_type, serial_number")

            return df

        except Exception as e:
            self.logger.error(f"Error adding partition columns: {e}", exc_info=True)
            return df

    def convert_to_parquet(self, df: pd.DataFrame) -> Optional[pa.Table]:
        """
        Convert DataFrame to PyArrow Table (Parquet format)

        Args:
            df: Pandas DataFrame

        Returns:
            PyArrow Table, or None if conversion failed
        """
        try:
            # Convert to PyArrow Table
            table = pa.Table.from_pandas(df)

            self.logger.info(f"✓ Converted to Parquet format ({table.num_rows} rows, {table.num_columns} columns)")

            # Log schema info
            self.logger.debug("Parquet schema:")
            for field in table.schema:
                self.logger.debug(f"  - {field.name}: {field.type}")

            return table

        except Exception as e:
            self.logger.error(f"Error converting to Parquet: {e}", exc_info=True)
            return None

    def generate_s3_key(self, partition_values: Dict[str, Any]) -> str:
        """
        Generate S3 key with Hive-style partitioning

        Format: s3://bucket/prefix/year=2025/month=11/day=13/hour=14/product_type=SERVER1/serial_number=1234/data.parquet

        Args:
            partition_values: Dictionary with partition column values

        Returns:
            S3 key path
        """
        # Build Hive-style partition path
        partition_path = "/".join([
            f"year={partition_values['year']}",
            f"month={partition_values['month']}",
            f"day={partition_values['day']}",
            f"hour={partition_values['hour']}",
            f"product_type={partition_values['product_type']}",
            f"serial_number={partition_values['serial_number']}"
        ])

        # Generate filename with timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"data_{timestamp}.parquet"

        # Combine prefix, partition path, and filename
        s3_key = f"{S3_KEY_PREFIX}{partition_path}/{filename}"

        return s3_key

    def upload_to_s3(self, table: pa.Table, s3_key: str) -> bool:
        """
        Upload Parquet table to S3

        Args:
            table: PyArrow Table
            s3_key: S3 key path

        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.s3_client:
                self.logger.error("S3 client not initialized")
                return False

            # Convert PyArrow Table to Parquet bytes
            self.logger.info(f"Writing Parquet data to S3: s3://{S3_BUCKET_NAME}/{s3_key}")

            # Write to in-memory buffer
            import io
            buffer = io.BytesIO()

            pq.write_table(
                table,
                buffer,
                compression=PARQUET_COMPRESSION,
                row_group_size=PARQUET_ROW_GROUP_SIZE,
                use_dictionary=True,  # Enable dictionary encoding for better compression
                write_statistics=True  # Write min/max statistics for query optimization
            )

            buffer.seek(0)

            # Upload to S3
            self.s3_client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=s3_key,
                Body=buffer.getvalue(),
                ContentType='application/x-parquet',
                Metadata={
                    'product_type': self.product_type,
                    'serial_number': self.serial_number,
                    'compression': PARQUET_COMPRESSION,
                    'row_group_size': str(PARQUET_ROW_GROUP_SIZE)
                }
            )

            file_size_mb = len(buffer.getvalue()) / (1024 * 1024)
            self.logger.info(f"✓ Uploaded to S3: {file_size_mb:.2f} MB")
            self.logger.info(f"  S3 URI: s3://{S3_BUCKET_NAME}/{s3_key}")

            return True

        except ClientError as e:
            self.logger.error(f"✗ S3 upload failed: {e}", exc_info=True)
            return False
        except Exception as e:
            self.logger.error(f"✗ Unexpected error during S3 upload: {e}", exc_info=True)
            return False

    def export_csv_to_s3_parquet(self, csv_file_path: Path) -> bool:
        """
        Main export function: Load CSV, convert to Parquet, and upload to S3

        Args:
            csv_file_path: Path to CSV file

        Returns:
            True if export successful, False otherwise
        """
        if not ENABLE_S3_EXPORT:
            self.logger.debug("S3 export disabled (ENABLE_S3_EXPORT=false)")
            return False

        if not self.s3_client:
            self.logger.error("S3 export failed: S3 client not initialized")
            return False

        self.logger.info("=" * 60)
        self.logger.info("STARTING S3 PARQUET EXPORT")
        self.logger.info("=" * 60)

        try:
            # Step 1: Load CSV
            df = self.load_csv_to_dataframe(csv_file_path)
            if df is None:
                return False

            # Step 2: Add partition columns
            df = self.add_partition_columns(df)

            # Step 3: Group by partition and export
            partition_cols = ['year', 'month', 'day', 'hour', 'product_type', 'serial_number']

            # Group by all partition columns
            grouped = df.groupby(partition_cols, as_index=False)

            total_partitions = len(grouped)
            self.logger.info(f"Data split into {total_partitions} partition(s)")

            success_count = 0
            for partition_values, group_df in grouped:
                # Create partition value dict
                partition_dict = dict(zip(partition_cols, partition_values))

                self.logger.info(f"Processing partition: {partition_dict}")

                # Remove partition columns from data (they're in the path)
                data_df = group_df.drop(columns=partition_cols)

                # Convert to Parquet
                table = self.convert_to_parquet(data_df)
                if table is None:
                    continue

                # Generate S3 key
                s3_key = self.generate_s3_key(partition_dict)

                # Upload to S3
                if self.upload_to_s3(table, s3_key):
                    success_count += 1

            self.logger.info("=" * 60)
            self.logger.info(f"S3 PARQUET EXPORT COMPLETE: {success_count}/{total_partitions} partitions uploaded")
            self.logger.info("=" * 60)

            return success_count == total_partitions

        except Exception as e:
            self.logger.error(f"Error during S3 Parquet export: {e}", exc_info=True)
            return False


def export_to_s3_parquet(csv_file_path: Path, product_type: str, serial_number: str, logger: logging.Logger) -> bool:
    """
    Convenience function to export CSV to S3 Parquet

    Args:
        csv_file_path: Path to CSV file
        product_type: Product type (from .env)
        serial_number: Serial number (from .env)
        logger: Logger instance

    Returns:
        True if successful, False otherwise
    """
    if not ENABLE_S3_EXPORT:
        logger.debug("S3 export disabled (ENABLE_S3_EXPORT=false)")
        return False

    exporter = S3ParquetExporter(product_type, serial_number, logger)
    return exporter.export_csv_to_s3_parquet(csv_file_path)


def test_s3_connection(logger: logging.Logger) -> bool:
    """
    Test S3 connection and bucket access

    Args:
        logger: Logger instance

    Returns:
        True if connection successful, False otherwise
    """
    try:
        logger.info("Testing S3 connection...")

        # Initialize S3 client
        if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
            s3_client = boto3.client(
                's3',
                region_name=AWS_REGION,
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY
            )
        else:
            s3_client = boto3.client('s3', region_name=AWS_REGION)

        # Test bucket access
        s3_client.head_bucket(Bucket=S3_BUCKET_NAME)

        logger.info(f"✓ S3 connection successful")
        logger.info(f"  Bucket: {S3_BUCKET_NAME}")
        logger.info(f"  Region: {AWS_REGION}")
        logger.info(f"  Prefix: {S3_KEY_PREFIX}")

        return True

    except NoCredentialsError:
        logger.error("✗ AWS credentials not found")
        return False
    except ClientError as e:
        logger.error(f"✗ S3 connection failed: {e}")
        return False
    except Exception as e:
        logger.error(f"✗ Unexpected error: {e}")
        return False


# Example usage (for testing)
if __name__ == "__main__":
    import logging

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logger = logging.getLogger(__name__)

    # Test S3 connection
    test_s3_connection(logger)

    # Example export
    csv_path = Path("/src/logs/pcp_parser_python/pmrep_output_20251113.csv")
    product_type = "SERVER1"
    serial_number = "1234"

    if csv_path.exists():
        export_to_s3_parquet(csv_path, product_type, serial_number, logger)
    else:
        logger.error(f"CSV file not found: {csv_path}")
