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
from influxdb_client import InfluxDBClient, Point, WriteOptions
from influxdb_client.client.write_api import SYNCHRONOUS

# Configuration from environment variables
WATCH_DIR = Path("/src/input/raw")
EXTRACT_DIR = Path("/tmp/pcp_archives")
PROCESSED_DIR = Path("/src/archive/processed")
FAILED_DIR = Path("/src/archive/failed")
LOG_DIR = Path("/src/logs/pcp_parser")
METRICS_CSV = LOG_DIR / "metrics_labels.csv"
VALIDATED_METRICS_CACHE = LOG_DIR / "validated_metrics.txt"

INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://influxdb:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "pcp-org")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "pcp-metrics")
INFLUXDB_MEASUREMENT = os.getenv("INFLUXDB_MEASUREMENT", "pcp_metrics")

# Static tags to enrich all data points
PRODUCT_TYPE = os.getenv("PRODUCT_TYPE", "L5E")
SERIAL_NUMBER = os.getenv("SERIAL_NUMBER", "341100896")

# Value filtering
PCP_METRICS_FILTER = os.getenv("PCP_METRICS_FILTER", "").lower()  # Options: "skip_zero", "skip_empty", "skip_none", or combination

# Performance tuning configuration
VALIDATION_BATCH_SIZE = int(os.getenv("VALIDATION_BATCH_SIZE", "100"))  # Metrics to validate per batch
INFLUX_BATCH_SIZE = int(os.getenv("INFLUX_BATCH_SIZE", "50000"))  # Data points per InfluxDB write
PROGRESS_LOG_INTERVAL = int(os.getenv("PROGRESS_LOG_INTERVAL", "50"))  # Log every N batches
SKIP_VALIDATION = os.getenv("SKIP_VALIDATION", "false").lower() == "true"  # Skip validation, use all metrics (RISKY!)
FORCE_REVALIDATE = os.getenv("FORCE_REVALIDATE", "false").lower() == "true"  # Force metric revalidation

# Metric category filters (set to "false" to exclude that category)
ENABLE_PROCESS_METRICS = os.getenv("ENABLE_PROCESS_METRICS", "false").lower() == "true"  # proc.* metrics (high cardinality)
ENABLE_DISK_METRICS = os.getenv("ENABLE_DISK_METRICS", "true").lower() == "true"  # disk.* metrics
ENABLE_FILE_METRICS = os.getenv("ENABLE_FILE_METRICS", "true").lower() == "true"  # vfs.* and filesys.* metrics
ENABLE_MEMORY_METRICS = os.getenv("ENABLE_MEMORY_METRICS", "true").lower() == "true"  # mem.* metrics
ENABLE_NETWORK_METRICS = os.getenv("ENABLE_NETWORK_METRICS", "true").lower() == "true"  # network.* metrics
ENABLE_KERNEL_METRICS = os.getenv("ENABLE_KERNEL_METRICS", "true").lower() == "true"  # kernel.* metrics
ENABLE_SWAP_METRICS = os.getenv("ENABLE_SWAP_METRICS", "true").lower() == "true"  # swap.* metrics
ENABLE_NFS_METRICS = os.getenv("ENABLE_NFS_METRICS", "false").lower() == "true"  # nfs.* metrics (often have PM_ERR_INDOM_LOG errors)

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

def load_validated_metrics_cache(logger) -> Optional[List[str]]:
    """Load cached validated metrics from file"""
    if FORCE_REVALIDATE:
        logger.info("FORCE_REVALIDATE=true, skipping cache")
        return None

    if not VALIDATED_METRICS_CACHE.exists():
        logger.info("No validation cache found, will validate metrics")
        return None

    try:
        with open(VALIDATED_METRICS_CACHE, 'r') as f:
            cached_metrics = [line.strip() for line in f if line.strip()]
        logger.info(f"Loaded {len(cached_metrics)} validated metrics from cache")
        return cached_metrics
    except Exception as e:
        logger.warning(f"Failed to load validation cache: {e}")
        return None

def save_validated_metrics_cache(metrics: List[str], logger):
    """Save validated metrics to cache file"""
    try:
        with open(VALIDATED_METRICS_CACHE, 'w') as f:
            for metric in metrics:
                f.write(f"{metric}\n")
        logger.info(f"Saved {len(metrics)} validated metrics to cache")
    except Exception as e:
        logger.warning(f"Failed to save validation cache: {e}")

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
    """Get list of available metrics from archive, validating each one works with pmrep"""
    logger.info("Discovering metrics in archive...")

    # Try to load from cache first (unless SKIP_VALIDATION or FORCE_REVALIDATE)
    if not SKIP_VALIDATION:
        cached_metrics = load_validated_metrics_cache(logger)
        if cached_metrics:
            logger.info(f"Using {len(cached_metrics)} cached validated metrics (skipping validation)")
            return cached_metrics

    try:
        # Get all metrics
        result = subprocess.run(
            ["pminfo", "-a", str(archive_base)],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            logger.error(f"pminfo failed: {result.stderr}")
            return []

        all_metric_names = [line.strip() for line in result.stdout.split('\n') if line.strip()]

        # If SKIP_VALIDATION is enabled, skip all validation and use all metrics (after filtering)
        if SKIP_VALIDATION:
            logger.warning(f"⚠️  SKIP_VALIDATION=true: Using all {len(all_metric_names)} metrics WITHOUT validation (may cause errors!)")
            valid_metrics = all_metric_names
            invalid_count = 0
        else:
            logger.info(f"Found {len(all_metric_names)} total metrics, validating each one...")
            valid_metrics = []
            invalid_count = 0
            batch_size = VALIDATION_BATCH_SIZE  # Test metrics in batches for speed (configurable)

            # Test metrics in batches to validate they work with pmrep
            for i in range(0, len(all_metric_names), batch_size):
                batch = all_metric_names[i:i+batch_size]

                # Try to fetch this batch with pmrep (--ignore-unknown skips invalid metrics)
                test_result = subprocess.run(
                    ["pmrep", "-a", str(archive_base), "-s", "1", "-o", "csv", "--ignore-unknown"] + batch,
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                # If batch succeeds, all metrics in it are valid
                if test_result.returncode == 0 and test_result.stdout.strip():
                    valid_metrics.extend(batch)
                else:
                    # Batch failed, test each metric individually
                    for metric in batch:
                        test_single = subprocess.run(
                            ["pmrep", "-a", str(archive_base), "-s", "1", "-o", "csv", "--ignore-unknown", metric],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        if test_single.returncode == 0 and test_single.stdout.strip():
                            valid_metrics.append(metric)
                        else:
                            invalid_count += 1

                # Progress update every 200 metrics
                if (i + batch_size) % 200 == 0:
                    logger.info(f"Validated {min(i + batch_size, len(all_metric_names))}/{len(all_metric_names)} metrics...")

        logger.info(f"Found {len(valid_metrics)} valid metrics (filtered out {invalid_count} invalid/derived metrics)")

        # Apply category filters
        original_count = len(valid_metrics)
        filtered_metrics = []
        filter_stats = {}

        for metric in valid_metrics:
            # Check each category filter
            if metric.startswith('proc.') and not ENABLE_PROCESS_METRICS:
                filter_stats['proc'] = filter_stats.get('proc', 0) + 1
                continue
            if metric.startswith('disk.') and not ENABLE_DISK_METRICS:
                filter_stats['disk'] = filter_stats.get('disk', 0) + 1
                continue
            if (metric.startswith('vfs.') or metric.startswith('filesys.')) and not ENABLE_FILE_METRICS:
                filter_stats['file'] = filter_stats.get('file', 0) + 1
                continue
            if metric.startswith('mem.') and not ENABLE_MEMORY_METRICS:
                filter_stats['mem'] = filter_stats.get('mem', 0) + 1
                continue
            if metric.startswith('network.') and not ENABLE_NETWORK_METRICS:
                filter_stats['network'] = filter_stats.get('network', 0) + 1
                continue
            if metric.startswith('kernel.') and not ENABLE_KERNEL_METRICS:
                filter_stats['kernel'] = filter_stats.get('kernel', 0) + 1
                continue
            if metric.startswith('swap.') and not ENABLE_SWAP_METRICS:
                filter_stats['swap'] = filter_stats.get('swap', 0) + 1
                continue
            if metric.startswith('nfs.') and not ENABLE_NFS_METRICS:
                filter_stats['nfs'] = filter_stats.get('nfs', 0) + 1
                continue

            # Metric passed all filters
            filtered_metrics.append(metric)

        # Log filtering results
        if filter_stats:
            total_filtered = sum(filter_stats.values())
            logger.info(f"Metric filtering: removed {total_filtered} metrics by category:")
            for category, count in sorted(filter_stats.items()):
                logger.info(f"  - {category}: {count} metrics filtered")
            logger.info(f"Remaining metrics: {len(filtered_metrics)} (reduced from {original_count})")
        else:
            logger.info(f"No category filters applied, using all {len(filtered_metrics)} valid metrics")

        valid_metrics = filtered_metrics

        # Save validated metrics to cache for future runs (only if validation was performed)
        if not SKIP_VALIDATION:
            save_validated_metrics_cache(valid_metrics, logger)
        else:
            logger.info("Skipping cache save (SKIP_VALIDATION=true)")

        # Log sample metrics
        logger.info("Sample valid metrics to export:")
        for metric in valid_metrics[:10]:
            logger.info(f"  - {metric}")
        if len(valid_metrics) > 10:
            logger.info(f"  ... and {len(valid_metrics) - 10} more")

        return valid_metrics

    except subprocess.TimeoutExpired:
        logger.error("Metric validation timed out")
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

def export_to_influxdb(archive_base: Path, logger, metrics: List[str]) -> bool:
    """Export metrics to InfluxDB using Python influxdb-client"""
    logger.info("===== STARTING EXPORT TO INFLUXDB =====")
    logger.info(f"Using Python InfluxDB client (pcp2influxdb uses v1 API, we need v2)")

    # Log active value filters
    if PCP_METRICS_FILTER:
        filters_active = []
        if "skip_zero" in PCP_METRICS_FILTER: filters_active.append("zero values")
        if "skip_empty" in PCP_METRICS_FILTER: filters_active.append("empty strings")
        if "skip_none" in PCP_METRICS_FILTER: filters_active.append("none/null values")
        if filters_active:
            logger.info(f"Value filtering ENABLED: skipping {', '.join(filters_active)}")
    else:
        logger.info("Value filtering DISABLED: all values will be exported")

    try:
        # Initialize InfluxDB client with async batching for parallel writes
        logger.info(f"Connecting to InfluxDB: {INFLUXDB_URL}")
        client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)

        # Use async write API with batching for parallel processing
        write_options = WriteOptions(
            batch_size=INFLUX_BATCH_SIZE,
            flush_interval=10_000,  # Flush every 10 seconds
            jitter_interval=2_000,
            retry_interval=5_000,
            max_retries=3,
            max_retry_delay=30_000,
            exponential_base=2
        )
        write_api = client.write_api(write_options=write_options)

        # Use pmrep with pre-validated metrics (all metrics have been tested and confirmed working)
        logger.info(f"Extracting metrics using pmrep with {len(metrics)} validated metrics...")

        # Build command with all validated metrics
        cmd = [
            "pmrep",
            "-a", str(archive_base),
            "-t", "1sec",
            "-o", "csv",
            "-U",  # Include timestamps
            "--ignore-unknown"  # Skip metrics that can't be read (prevents PM_ERR_* errors)
        ] + metrics  # Add all validated metrics (already tested to work)

        logger.info(f"Command: pmrep -a {archive_base} -t 1sec -o csv -U --ignore-unknown [+ {len(metrics)} metrics]")

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

                        # Track this metric in CSV (for all valid numeric values, even zeros)
                        save_metric_to_csv(metric_name)

                        # Skip None values
                        if value is None:
                            error_count += 1
                            continue

                        # Apply PCP_METRICS_FILTER
                        if PCP_METRICS_FILTER:
                            # Check if value should be filtered
                            if "skip_zero" in PCP_METRICS_FILTER and value == 0:
                                continue
                            if "skip_empty" in PCP_METRICS_FILTER and value_str.strip() == "":
                                continue
                            if "skip_none" in PCP_METRICS_FILTER and (value_str.lower() == "none" or value_str.strip() == ""):
                                continue

                        # Create InfluxDB point with static tags
                        point = Point(INFLUXDB_MEASUREMENT) \
                            .tag("metric", metric_name) \
                            .tag("product_type", PRODUCT_TYPE) \
                            .tag("serialNumber", SERIAL_NUMBER) \
                            .field("value", value) \
                            .time(ts)

                        points.append(point)

                    except ValueError:
                        error_count += 1

                # Write points in batches (configurable size for performance)
                if len(points) >= INFLUX_BATCH_SIZE:
                    write_api.write(bucket=INFLUXDB_BUCKET, record=points)
                    total_points_written += len(points)
                    batch_count += 1
                    # Log progress at configurable intervals
                    if batch_count % PROGRESS_LOG_INTERVAL == 0:
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

        # Flush async writes and wait for completion
        logger.info("Flushing async writes to InfluxDB...")
        write_api.flush()
        logger.info("All async writes completed")

        # Check for errors (filter out known harmless warnings)
        stderr = process.stderr.read()
        if stderr:
            # Filter out known harmless warnings that --ignore-unknown handles
            harmless_patterns = [
                "PM_ERR_INDOM_LOG",  # Instance domain not defined (expected with --ignore-unknown)
                "PM_ERR_BADDERIVE",  # Invalid derived metric (expected with --ignore-unknown)
                "Invalid metric"     # Generic invalid metric message
            ]

            # Split stderr into lines and filter
            stderr_lines = stderr.strip().split('\n')
            filtered_stderr = []

            for line in stderr_lines:
                # Skip line if it contains any harmless pattern
                if not any(pattern in line for pattern in harmless_patterns):
                    filtered_stderr.append(line)

            # Only log if there are real errors (not filtered out)
            if filtered_stderr:
                logger.warning(f"pmrep stderr: {chr(10).join(filtered_stderr)}")

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

    # Start timing the entire archive processing
    start_time_total = time.time()

    try:
        # Create extraction directory
        extract_path.mkdir(parents=True, exist_ok=True)

        # Extract the archive
        logger.info(f"Extracting archive...")
        start_time_extract = time.time()
        with tarfile.open(archive_path, 'r:xz') as tar:
            tar.extractall(extract_path)
        extract_duration = time.time() - start_time_extract
        logger.info(f"Extracted to {extract_path} in {extract_duration:.2f} seconds")

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
        logger.info(f"Starting metric validation...")
        start_time_validation = time.time()
        metrics = get_available_metrics(archive_base, logger)
        validation_duration = time.time() - start_time_validation
        logger.info(f"Metric validation completed in {validation_duration:.2f} seconds")

        if not metrics:
            logger.warning("No metrics found in archive")
            shutil.move(str(archive_path), str(FAILED_DIR / archive_name))
            logger.info(f"Moved to failed directory: {archive_name}")
            return False

        # Get sample metric values for logging
        get_metric_values(archive_base, metrics, logger)

        # Check InfluxDB connectivity
        check_influxdb_connection(logger)

        # Export to InfluxDB (pass discovered metrics)
        logger.info(f"Starting InfluxDB export...")
        start_time_export = time.time()
        success = export_to_influxdb(archive_base, logger, metrics)
        export_duration = time.time() - start_time_export
        logger.info(f"InfluxDB export completed in {export_duration:.2f} seconds")

        # Calculate total processing time
        total_duration = time.time() - start_time_total
        minutes = int(total_duration // 60)
        seconds = total_duration % 60

        if success:
            logger.info(f"✓ Successfully exported {archive_name} to InfluxDB")
            logger.info(f"InfluxDB: {INFLUXDB_URL}, Org: {INFLUXDB_ORG}, Bucket: {INFLUXDB_BUCKET}")
            logger.info(f"⏱️  TOTAL PROCESSING TIME: {minutes} minutes {seconds:.2f} seconds")
            logger.info(f"   ├─ Extraction: {extract_duration:.2f}s")
            logger.info(f"   ├─ Validation: {validation_duration:.2f}s")
            logger.info(f"   └─ Export: {export_duration:.2f}s")

            # Remove processed archive
            archive_path.unlink()
            logger.info(f"✓ Removed {archive_name}")
        else:
            logger.error(f"✗ Failed to export {archive_name} to InfluxDB")
            logger.error(f"⏱️  TOTAL PROCESSING TIME (FAILED): {minutes} minutes {seconds:.2f} seconds")
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
    logger.info(f"Static Tags - Product Type: {PRODUCT_TYPE}, Serial Number: {SERIAL_NUMBER}")
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
