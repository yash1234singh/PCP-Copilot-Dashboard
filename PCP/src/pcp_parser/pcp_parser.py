#!/usr/bin/env python3
"""
PCP Archive to InfluxDB Processor
Monitors for .tar.xz PCP archives, extracts and exports metrics to InfluxDB
"""

import os
import sys
import time
import tarfile
import shutil
import subprocess
import logging
import json
import re
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any, Set
import requests
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

# Configuration from environment variables
WATCH_DIR = Path("/src/input/raw")
EXTRACT_DIR = Path("/tmp/pcp_archives")
PROCESSED_DIR = Path("/src/archive/processed")
FAILED_DIR = Path("/src/archive/failed")
LOG_DIR = Path("/src/logs/pcp_parser")
METRICS_CSV = LOG_DIR / "metrics_labels.csv"

INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://influxdb:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "pcp-org")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "pcp-metrics")
INFLUXDB_MEASUREMENT = os.getenv("INFLUXDB_MEASUREMENT", "pcp_metrics")

# Static tags to enrich all data points
HOST_NAME = os.getenv("HOST_NAME", "ABC")
HOST_NUM = os.getenv("HOST_NUM", "123")

# Global set to track metrics in memory
_metrics_cache: Set[str] = set()

# Setup logging
def setup_logging():
    """Configure logging to both console and file"""
    # Ensure log directory exists
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_file = LOG_DIR / "pcp_parser.log"

    # Create formatters
    file_formatter = logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    console_formatter = logging.Formatter('%(message)s')

    # File handler
    file_handler = logging.FileHandler(log_file, mode='a')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)

    # Root logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

def log_separator(logger, title: str):
    """Log a separator line with title"""
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)

def load_metrics_cache():
    """Load existing metrics from CSV into memory cache"""
    global _metrics_cache
    if METRICS_CSV.exists():
        with open(METRICS_CSV, 'r', newline='') as f:
            reader = csv.reader(f)
            next(reader, None)  # Skip header
            _metrics_cache = {row[0] for row in reader if row}
    else:
        _metrics_cache = set()

def save_metric_to_csv(metric_name: str):
    """Add a new metric to the CSV file if it doesn't exist"""
    global _metrics_cache

    if metric_name in _metrics_cache:
        return  # Already tracked

    # Add to cache
    _metrics_cache.add(metric_name)

    # Write to CSV
    file_exists = METRICS_CSV.exists()
    with open(METRICS_CSV, 'a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['metric_name'])  # Header
        writer.writerow([metric_name])

def check_influxdb_connection(logger) -> bool:
    """Test connectivity to InfluxDB"""
    try:
        logger.info("Testing InfluxDB connectivity...")
        response = requests.get(f"{INFLUXDB_URL}/ping", timeout=5)
        logger.info(f"InfluxDB is reachable (HTTP {response.status_code})")
        return True
    except Exception as e:
        logger.warning(f"InfluxDB connectivity issue: {e}")
        return False

def get_available_metrics(archive_base: Path, logger) -> List[str]:
    """Get list of available psoc metrics from archive"""
    logger.info("Discovering available metrics in archive...")

    try:
        # Get all psoc metrics
        result = subprocess.run(
            ["pminfo", "-a", str(archive_base), "psoc"],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            logger.error(f"pminfo failed: {result.stderr}")
            return []

        metrics = [line.strip() for line in result.stdout.split('\n') if line.strip()]
        logger.info(f"Found {len(metrics)} psoc metrics to export")

        # Log sample metrics
        logger.info("Sample metrics to export:")
        for metric in metrics[:10]:
            logger.info(f"  - {metric}")
        if len(metrics) > 10:
            logger.info(f"  ... and {len(metrics) - 10} more")

        return metrics

    except subprocess.TimeoutExpired:
        logger.error("pminfo command timed out")
        return []
    except Exception as e:
        logger.error(f"Error getting metrics: {e}")
        return []

def get_metric_values(archive_base: Path, metrics: List[str], logger) -> dict:
    """Get sample values for metrics to log"""
    metric_values = {}

    logger.info("Getting sample values for first 10 metrics...")
    for metric in metrics[:10]:
        try:
            result = subprocess.run(
                ["pmval", "-a", str(archive_base), "-t", "1", "-s", "1", metric],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                # Look for the data line (format: HH:MM:SS value)
                for line in lines:
                    if ':' in line and not line.startswith('metric'):
                        metric_values[metric] = line.strip()
                        logger.info(f"  {metric}: {line.strip()}")
                        break
        except Exception as e:
            logger.debug(f"Could not get value for {metric}: {e}")

    return metric_values

def export_to_influxdb(archive_base: Path, logger) -> bool:
    """Export metrics to InfluxDB using Python influxdb-client"""
    logger.info("===== STARTING EXPORT TO INFLUXDB =====")
    logger.info(f"Using Python InfluxDB client (pcp2influxdb uses v1 API, we need v2)")

    try:
        # Initialize InfluxDB client
        logger.info(f"Connecting to InfluxDB: {INFLUXDB_URL}")
        client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
        write_api = client.write_api(write_options=SYNCHRONOUS)

        # Use pmrep to export data in CSV format
        logger.info(f"Extracting metrics using pmrep...")

        cmd = [
            "pmrep",
            "-a", str(archive_base),
            "-t", "1sec",
            "-o", "csv",
            "-U",  # Include timestamps
            "psoc"  # All psoc metrics
        ]

        logger.info(f"Command: pmrep -a {archive_base} -t 1sec -o csv -U psoc")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        # Read CSV output and convert to InfluxDB points
        points = []
        header = None
        line_count = 0
        error_count = 0
        total_points_written = 0
        batch_count = 0

        logger.info("Processing pmrep output...")

        for line in process.stdout:
            line = line.strip()
            if not line:
                continue

            line_count += 1

            # First line is header
            if header is None:
                header = [col.strip().strip('"') for col in line.split(',')]
                logger.info(f"Found {len(header)} columns (first column is timestamp)")
                continue

            try:
                # Parse CSV line
                values = line.split(',')
                if len(values) != len(header):
                    continue

                # First column is timestamp
                timestamp_str = values[0].strip()

                # Parse timestamp (format: YYYY-MM-DD HH:MM:SS)
                try:
                    ts = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                    ts = ts.replace(tzinfo=timezone.utc)
                except:
                    continue

                # Create points for each metric
                for i, metric_name in enumerate(header[1:], start=1):
                    value_str = values[i].strip().strip('"')

                    # Skip empty, None, N/A, or ? values
                    if not value_str or value_str.lower() in ['', 'n/a', '?', 'none', 'null']:
                        error_count += 1  # Count empty values
                        continue

                    try:
                        value = float(value_str)

                        # Skip zero values and None
                        if value == 0 or value is None:
                            error_count += 1
                            continue

                        # Track this metric in CSV (only if has non-zero data)
                        save_metric_to_csv(metric_name)

                        # Create InfluxDB point with static tags
                        point = Point(INFLUXDB_MEASUREMENT) \
                            .tag("metric", metric_name) \
                            .tag("host_name", HOST_NAME) \
                            .tag("host_num", HOST_NUM) \
                            .field("value", value) \
                            .time(ts)

                        points.append(point)

                    except ValueError:
                        error_count += 1

                # Write points in batches of 5000 (reduced log frequency)
                if len(points) >= 5000:
                    write_api.write(bucket=INFLUXDB_BUCKET, record=points)
                    total_points_written += len(points)
                    batch_count += 1
                    # Log every 10 batches (50k points)
                    if batch_count % 10 == 0:
                        logger.info(f"Progress: {total_points_written} points written ({batch_count} batches)...")
                    points = []

            except Exception as e:
                error_count += 1
                if error_count <= 5:
                    logger.debug(f"Error processing line {line_count}: {e}")

        # Wait for process to complete
        process.wait(timeout=300)

        # Write remaining points
        if points:
            write_api.write(bucket=INFLUXDB_BUCKET, record=points)
            total_points_written += len(points)
            logger.info(f"Writing final batch of {len(points)} points to InfluxDB...")

        # Check for errors
        stderr = process.stderr.read()
        if stderr:
            logger.warning(f"pmrep stderr: {stderr}")

        logger.info(f"===== EXPORT COMPLETE =====")
        logger.info(f"Total data points written: {total_points_written}")
        logger.info(f"Processed {line_count} lines from pmrep")
        logger.info(f"Empty/invalid values skipped: {error_count}")

        client.close()
        return True

    except subprocess.TimeoutExpired:
        logger.error("pmrep timed out after 5 minutes")
        if 'process' in locals():
            process.kill()
        return False
    except Exception as e:
        logger.error(f"Error exporting to InfluxDB: {e}", exc_info=True)
        return False

def process_archive(archive_path: Path, logger) -> bool:
    """Process a single tar.xz archive"""
    archive_name = archive_path.name
    extract_path = EXTRACT_DIR / archive_path.stem

    log_separator(logger, f"Processing archive: {archive_name}")
    logger.info(f"START: Processing {archive_name}")

    try:
        # Create extraction directory
        extract_path.mkdir(parents=True, exist_ok=True)

        # Extract the archive
        logger.info(f"Extracting archive...")
        with tarfile.open(archive_path, 'r:xz') as tar:
            tar.extractall(extract_path)
        logger.info(f"Extracted to {extract_path}")

        # Find the PCP archive (look for .meta file)
        meta_files = list(extract_path.rglob("*.meta"))

        if not meta_files:
            logger.error(f"No PCP archive found in {archive_name}")
            shutil.move(str(archive_path), str(FAILED_DIR / archive_name))
            logger.info(f"Moved to failed directory: {archive_name}")
            return False

        # Get archive base path (remove .meta extension)
        archive_base = Path(str(meta_files[0])[:-5])  # Remove .meta
        logger.info(f"Found PCP archive: {archive_base}")

        # Get available metrics
        metrics = get_available_metrics(archive_base, logger)

        if not metrics:
            logger.warning("No metrics found in archive")
            shutil.move(str(archive_path), str(FAILED_DIR / archive_name))
            logger.info(f"Moved to failed directory: {archive_name}")
            return False

        # Get sample metric values for logging
        get_metric_values(archive_base, metrics, logger)

        # Check InfluxDB connectivity
        check_influxdb_connection(logger)

        # Export to InfluxDB
        success = export_to_influxdb(archive_base, logger)

        if success:
            logger.info(f"✓ Successfully exported {archive_name} to InfluxDB")
            logger.info(f"InfluxDB: {INFLUXDB_URL}, Org: {INFLUXDB_ORG}, Bucket: {INFLUXDB_BUCKET}")

            # Remove processed archive
            archive_path.unlink()
            logger.info(f"✓ Removed {archive_name}")
        else:
            logger.error(f"✗ Failed to export {archive_name} to InfluxDB")
            shutil.move(str(archive_path), str(FAILED_DIR / archive_name))
            logger.info(f"✓ Moved failed {archive_name} to {FAILED_DIR}")

        logger.info(f"COMPLETE: Finished processing {archive_name}")
        return success

    except Exception as e:
        logger.error(f"Error processing {archive_name}: {e}", exc_info=True)
        try:
            shutil.move(str(archive_path), str(FAILED_DIR / archive_name))
            logger.info(f"Moved to failed directory: {archive_name}")
        except:
            pass
        return False
    finally:
        # Cleanup extraction directory
        if extract_path.exists():
            shutil.rmtree(extract_path, ignore_errors=True)

def main():
    """Main monitoring loop"""
    logger = setup_logging()

    logger.info("=" * 60)
    logger.info("PCP Archive to InfluxDB Processor (Python)")
    logger.info("=" * 60)
    logger.info(f"Watch directory: {WATCH_DIR}")
    logger.info(f"Extract directory: {EXTRACT_DIR}")
    logger.info(f"Processed directory: {PROCESSED_DIR}")
    logger.info(f"Failed directory: {FAILED_DIR}")
    logger.info(f"Log directory: {LOG_DIR}")
    logger.info(f"InfluxDB URL: {INFLUXDB_URL}")
    logger.info(f"InfluxDB Measurement: {INFLUXDB_MEASUREMENT}")
    logger.info(f"Static Tags - Host Type Type: {HOST_NAME}, Host Number: {HOST_NUM}")
    logger.info("")

    # Create necessary directories
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    FAILED_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing metrics from CSV
    load_metrics_cache()
    logger.info(f"Loaded {len(_metrics_cache)} existing metrics from cache")

    # Wait for InfluxDB to be ready
    logger.info("Waiting for InfluxDB to be ready...")
    while True:
        try:
            response = requests.get(f"{INFLUXDB_URL}/ping", timeout=5)
            if response.status_code in [200, 204]:
                logger.info("InfluxDB is ready!")
                break
        except:
            logger.info("InfluxDB is unavailable - sleeping")
            time.sleep(5)

    logger.info("")
    logger.info("Starting continuous monitoring loop...")
    logger.info("Checking every 10 seconds for new .tar.xz files")
    logger.info("")

    # Main monitoring loop
    while True:
        try:
            logger.info(f"Checking for .tar.xz files in {WATCH_DIR}...")

            # Find all .tar.xz files
            archive_files = list(WATCH_DIR.glob("*.tar.xz"))

            if archive_files:
                for archive in archive_files:
                    logger.info(f"Found file: {archive.name}")
                    process_archive(archive, logger)
            else:
                logger.info("No files found. Sleeping for 10 seconds...")

            time.sleep(10)

        except KeyboardInterrupt:
            logger.info("Received interrupt signal, shutting down...")
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
            time.sleep(10)

if __name__ == "__main__":
    main()
