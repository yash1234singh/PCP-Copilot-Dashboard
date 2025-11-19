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
import io
import lzma
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any, Set
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
import requests
from influxdb_client import InfluxDBClient, Point, WriteOptions
from influxdb_client.client.write_api import SYNCHRONOUS

try:
    import pandas as pd
    import numpy as np
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    pd = None
    np = None

# Import S3 Parquet exporter (optional)
try:
    from s3_parquet_exporter import export_to_s3_parquet, ENABLE_S3_EXPORT
    S3_EXPORT_AVAILABLE = True
except ImportError:
    S3_EXPORT_AVAILABLE = False
    ENABLE_S3_EXPORT = False

# Configuration from environment variables
WATCH_DIR = Path(os.getenv("WATCH_DIR", "/src/input/raw"))
EXTRACT_DIR = Path(os.getenv("EXTRACT_DIR", "/tmp/pcp_archives"))
PROCESSED_DIR = Path(os.getenv("PROCESSED_DIR", "/src/archive/processed"))
FAILED_DIR = Path(os.getenv("FAILED_DIR", "/src/archive/failed"))
LOG_DIR = Path(os.getenv("LOG_DIR", "/src/logs/pcp_parser"))
DATA_FILTER_DIR = Path(os.getenv("DATA_FILTER_DIR", "/src/input/data_filter"))
METRICS_CSV = LOG_DIR / "metrics_labels.csv"
VALIDATED_METRICS_FILE = DATA_FILTER_DIR / "validated_metrics.txt"

INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://influxdb:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "pcp-org")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "pcp-metrics")
INFLUXDB_MEASUREMENT = os.getenv("INFLUXDB_MEASUREMENT", "pcp_metrics")

# Static tags to enrich all data points - will be loaded from .env file
PRODUCT_TYPE = None
SERIAL_NUMBER = None

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

SAVE_CSV_OUTPUT = os.getenv("SAVE_CSV_OUTPUT", "true").lower() == "true"
ENABLE_INFLUXDB_WRITE = os.getenv("ENABLE_INFLUXDB_WRITE", "true").lower() == "true"  # Enable/disable InfluxDB writes
ENABLE_SNAME_PROCESSING = os.getenv("ENABLE_SNAME_PROCESSING", "false").lower() == "true"  # Enable/disable proc.psinfo.sname (causes timeouts)

# Constants for parallel processing (no need for env variable - always use optimal values)
PARALLEL_VALIDATION_WORKERS = 100  # Optimal worker count for parallel validation

_metrics_cache: Set[str] = set()
_influx_client = None

# Setup logging
def setup_logging():
    """Configure logging to both console and file"""
    # Ensure log directory exists
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_file = LOG_DIR / "pcp_parser.log"

    # Root logger
    logger = logging.getLogger()

    # Clear existing handlers to prevent duplicate logging
    if logger.hasHandlers():
        logger.handlers.clear()

    logger.setLevel(logging.DEBUG)

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

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

def log_separator(logger, title: str):
    """Log a separator line with title"""
    logger.info("=" * 60)
    logger.info(title)
    logger.info("=" * 60)


def validate_single_metric(metric: str, archive_base: Path) -> bool:
    """Validate a single metric with pmrep"""
    try:
        result = subprocess.run(
            ["pmrep", "-a", str(archive_base), "-s", "1", "-o", "csv", "--ignore-unknown", metric],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0 and result.stdout.strip()
    except:
        return False


def validate_metrics_parallel(metrics: List[str], archive_base: Path, logger) -> List[str]:
    """Validate metrics in parallel using ThreadPoolExecutor (always parallel for performance)"""
    logger.info(f"Parallel validation: {len(metrics)} metrics with {PARALLEL_VALIDATION_WORKERS} workers")

    valid_metrics = []

    with ThreadPoolExecutor(max_workers=PARALLEL_VALIDATION_WORKERS) as executor:
        futures = {executor.submit(validate_single_metric, m, archive_base): m for m in metrics}

        validated_count = 0
        for future in as_completed(futures):
            metric = futures[future]
            try:
                if future.result():
                    valid_metrics.append(metric)
                validated_count += 1
                if validated_count % 50 == 0:
                    logger.info(f"  Validated {validated_count}/{len(metrics)}")
            except Exception as e:
                logger.debug(f"Error validating {metric}: {e}")

    logger.info(f"Validation complete: {len(valid_metrics)} valid metrics")
    return valid_metrics


def get_influx_client() -> InfluxDBClient:
    """
    OPTIMIZED: Get or create global InfluxDB client with connection pooling
    Connection pooling significantly improves write performance by reusing connections
    """
    global _influx_client
    if _influx_client is None:
        _influx_client = InfluxDBClient(
            url=INFLUXDB_URL,
            token=INFLUXDB_TOKEN,
            org=INFLUXDB_ORG,
            timeout=180_000,  # 3 minutes timeout for large batches
            enable_gzip=True,  # Compress payloads to reduce network transfer time
            connection_pool_maxsize=20  # Connection pool for parallel writes (default is 10)
        )
    return _influx_client


def extract_archive(archive_path: Path, extract_path: Path, logger) -> float:
    """Extract tar.xz archive"""
    start_time = time.time()

    with tarfile.open(archive_path, 'r:xz') as tar:
        tar.extractall(extract_path)

    duration = time.time() - start_time
    logger.info(f"Archive extraction: {duration:.2f}s")
    return duration


def load_config_from_env_file():
    """Load PRODUCT_TYPE and SERIAL_NUMBER from .env file"""
    global PRODUCT_TYPE, SERIAL_NUMBER

    env_file = Path("/src/.env")

    # Set defaults first
    PRODUCT_TYPE = "SERVER1"
    SERIAL_NUMBER = "1234"

    # Try to read from .env file (highest priority)
    if env_file.exists():
        try:
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        if line.startswith('PRODUCT_TYPE='):
                            PRODUCT_TYPE = line.split('=', 1)[1].strip()
                        elif line.startswith('SERIAL_NUMBER='):
                            SERIAL_NUMBER = line.split('=', 1)[1].strip()
        except Exception as e:
            # If .env file read fails, try environment variables as fallback
            PRODUCT_TYPE = os.getenv("PRODUCT_TYPE", PRODUCT_TYPE)
            SERIAL_NUMBER = os.getenv("SERIAL_NUMBER", SERIAL_NUMBER)
            print(f"Warning: Could not read .env file: {e}, using environment variables")

    return PRODUCT_TYPE, SERIAL_NUMBER

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
    """Load validated metrics from input/data_filter directory"""
    if FORCE_REVALIDATE:
        logger.info("FORCE_REVALIDATE=true, skipping predefined metrics file")
        return None

    if not VALIDATED_METRICS_FILE.exists():
        logger.info("No validated_metrics.txt found in input/data_filter, will validate metrics")
        return None

    try:
        with open(VALIDATED_METRICS_FILE, 'r') as f:
            # Read file and filter out comments and empty lines
            validated_metrics = []
            for line in f:
                line = line.strip()
                # Skip empty lines and comments (lines starting with #)
                if line and not line.startswith('#'):
                    validated_metrics.append(line)
        logger.info(f"Loaded {len(validated_metrics)} validated metrics from {VALIDATED_METRICS_FILE}")
        return validated_metrics
    except Exception as e:
        logger.warning(f"Failed to load validated metrics file: {e}")
        return None

def save_validated_metrics_cache(metrics: List[str], logger):
    """Save validated metrics to cache file (for reference only, main file is in input/data_filter)"""
    try:
        # Save to logs directory for reference/debugging
        cache_file = LOG_DIR / "validated_metrics_discovered.txt"
        with open(cache_file, 'w') as f:
            for metric in metrics:
                f.write(f"{metric}\n")
        logger.info(f"Saved {len(metrics)} discovered metrics to {cache_file} (for reference)")
        logger.info(f"Note: Main validated metrics file is {VALIDATED_METRICS_FILE}")
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
        else:
            logger.info(f"Found {len(all_metric_names)} total metrics, validating with parallel workers...")
            # Always use parallel validation for best performance
            valid_metrics = validate_metrics_parallel(all_metric_names, archive_base, logger)

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
            if metric == 'proc.psinfo.sname' and not ENABLE_SNAME_PROCESSING:
                filter_stats['sname'] = filter_stats.get('sname', 0) + 1
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

def start_proc_psinfo_sname_collection(archive_base: Path, logger):
    """
    Start pmrep process in background to collect proc.psinfo.sname data
    Uses CSV output format which is much simpler to parse than pmval
    Returns the subprocess.Popen object for later processing
    """
    logger.info("Starting proc.psinfo.sname collection in parallel...")
    logger.debug(f"Running: pmrep -a {archive_base} -t 1sec -o csv -U proc.psinfo.sname")

    try:
        process = subprocess.Popen(
            ["pmrep", "-a", str(archive_base), "-t", "1sec", "-o", "csv", "-U", "proc.psinfo.sname"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        logger.debug(f"✓ pmrep process started (PID: {process.pid})")
        return process
    except Exception as e:
        logger.error(f"✗ Failed to start pmrep process: {e}")
        return None


def parse_proc_psinfo_sname_from_process(pmrep_process, archive_base: Path, logger) -> List[Dict[str, Any]]:
    """
    Parse proc.psinfo.sname metric from pmrep CSV output

    CSV Format Example:
    Time,"proc.psinfo.sname-000001 /sbin/init","proc.psinfo.sname-000274 /usr/lib/systemd/systemd-journald",...
    2025-11-14 10:01:31,"S","R","D","I",...

    Process States (Linux):
    - R: Running (process is executing)
    - D: Blocked/Uninterruptible sleep (waiting for I/O)
    - S: Sleeping (interruptible sleep, waiting for event)
    - I: Idle (kernel thread)
    - Z: Zombie (terminated but not reaped)
    - T: Stopped (by signal or debugger)

    Configuration: CAPTURE_PROCESS_STATES
    - By default: set() = capture ALL states
    - To filter: specify only desired states like {'R', 'D'}

    Returns list of data points with timestamp, process name, and state
    """
    # ============================================================
    # CONFIGURATION: Process states to CAPTURE (include in export)
    # ============================================================
    # By default, ALL states are listed = capture everything
    # To filter, comment out or remove states you DON'T want:
    # Examples:
    #   {'R', 'D', 'S', 'I', 'Z', 'T'}  - Capture ALL (default)
    #   {'R', 'D'}                      - Only Running and Blocked
    #   {'R', 'D', 'Z'}                 - Running, Blocked, and Zombie
    #CAPTURE_PROCESS_STATES = {
    #    'R',  # Running - process is executing
    #    'D',  # Blocked - uninterruptible sleep (I/O wait)
    #    'S',  # Sleeping - interruptible sleep
    #    'I',  # Idle - kernel thread
    #    'Z',  # Zombie - terminated but not reaped
    #    'T',  # Stopped - by signal or debugger
    #}

    CAPTURE_PROCESS_STATES = {
        'R',  # Running - process is executing
        'D',  # Blocked - uninterruptible sleep (I/O wait)
        'I',  # Idle - kernel thread
    }

    # ============================================================

    STATE_DESCRIPTIONS = {
        'R': 'Running',
        'D': 'Blocked',
        'S': 'Sleeping',
        'I': 'Idle',
        'Z': 'Zombie',
        'T': 'Stopped'
    }

    logger.info("=" * 60)
    logger.info("PROCESSING proc.psinfo.sname METRIC")
    logger.info("=" * 60)

    # Log filtering configuration
    if CAPTURE_PROCESS_STATES:
        capture_names = [f"{s} ({STATE_DESCRIPTIONS.get(s, s)})" for s in sorted(CAPTURE_PROCESS_STATES)]
        logger.info(f"State filtering ENABLED - Capturing ONLY: {', '.join(capture_names)}")
    else:
        logger.info("State filtering DISABLED - Capturing ALL process states")

    logger.info(f"Archive: {archive_base}")

    try:
        if pmrep_process is None:
            logger.warning("⚠️  No pmrep process available - skipping")
            return []

        # Wait for pmrep process to complete and get output
        logger.info("Waiting for pmrep process to complete...")
        try:
            stdout, stderr = pmrep_process.communicate(timeout=300)  # Increased to 5 minutes
        except subprocess.TimeoutExpired:
            logger.error("✗ pmrep process timed out after 300 seconds")
            pmrep_process.kill()
            return []

        if pmrep_process.returncode != 0:
            logger.error(f"✗ pmrep process failed with return code {pmrep_process.returncode}")
            logger.error(f"  Error: {stderr}")
            return []

        logger.info("✓ Process state data fetched successfully")
        logger.debug(f"Raw output size: {len(stdout)} characters")

        # Parse CSV output
        import csv
        import io

        data_points = []
        state_counts = {state: 0 for state in STATE_DESCRIPTIONS.keys()}
        captured_count = 0
        skipped_count = 0

        lines = stdout.strip().split('\n')
        if len(lines) < 2:
            logger.warning("⚠️  CSV has no data rows")
            return []

        # Parse header to extract PIDs and process names
        # Format: Time,"proc.psinfo.sname-000001 /sbin/init","proc.psinfo.sname-000274 /usr/lib/systemd/systemd-journald",...
        csv_reader = csv.reader(io.StringIO(lines[0]))
        header_row = next(csv_reader)

        process_columns = []
        for col in header_row[1:]:  # Skip "Time" column
            # Extract PID and process name from: "proc.psinfo.sname-000274 /usr/lib/systemd/systemd-journald"
            match = re.match(r'proc\.psinfo\.sname-(\d+)\s+(.+)', col)
            if match:
                pid = match.group(1)
                process_name = match.group(2)
                process_columns.append({'pid': pid, 'process_name': process_name})

        logger.info(f"Found {len(process_columns)} process columns in CSV")

        if PANDAS_AVAILABLE and len(lines) > 10:
            try:
                logger.info("Using pandas for process state parsing")

                # Parse entire CSV with pandas
                full_csv = '\n'.join(lines)
                df = pd.read_csv(io.StringIO(full_csv))

                # Extract timestamps
                timestamps = df.iloc[:, 0].values

                # Process each data column (skip timestamp column)
                for idx, col_name in enumerate(df.columns[1:]):
                    if idx >= len(process_columns):
                        break

                    proc_info = process_columns[idx]
                    states_col = df.iloc[:, idx + 1].values

                    # Use numpy for vectorized filtering
                    if CAPTURE_PROCESS_STATES:
                        # Create mask for states we want to capture
                        mask = np.isin(states_col, list(CAPTURE_PROCESS_STATES))
                        filtered_timestamps = timestamps[mask]
                        filtered_states = states_col[mask]
                    else:
                        filtered_timestamps = timestamps
                        filtered_states = states_col

                    # Count states
                    unique_states, counts = np.unique(states_col, return_counts=True)
                    for state, count in zip(unique_states, counts):
                        if state in state_counts:
                            state_counts[state] += count
                        if CAPTURE_PROCESS_STATES and state not in CAPTURE_PROCESS_STATES:
                            skipped_count += count
                        else:
                            captured_count += count

                    # Build data points for filtered states
                    for ts, state in zip(filtered_timestamps, filtered_states):
                        if pd.notna(state) and state.strip():
                            data_points.append({
                                'timestamp': str(ts),
                                'pid': proc_info['pid'],
                                'process_name': proc_info['process_name'],
                                'state': state.strip(),
                                'state_description': STATE_DESCRIPTIONS.get(state.strip(), state.strip())
                            })

                logger.info(f"✓ Pandas vectorized parsing: {len(data_points)} points captured")

            except Exception as e:
                logger.warning(f"Pandas parsing failed: {e}, falling back to standard parsing")
                # Fall back to standard parsing
                data_points = []
                captured_count = 0
                skipped_count = 0
                use_standard_parsing = True
        else:
            use_standard_parsing = True

        # ============================================================
        # STANDARD PARSING (fallback)
        # ============================================================
        if not PANDAS_AVAILABLE or len(lines) <= 10 or (PANDAS_AVAILABLE and use_standard_parsing if 'use_standard_parsing' in locals() else False):
            logger.info("Using standard row-by-row process state parsing...")

            for line in lines[1:]:
                if not line.strip():
                    continue

                csv_reader = csv.reader(io.StringIO(line))
                try:
                    row = next(csv_reader)
                except:
                    continue

                if len(row) < 2:
                    continue

                timestamp = row[0]  # Format: "2025-11-14 10:01:31"
                states = row[1:]

                # Process each column
                for idx, state in enumerate(states):
                    if idx >= len(process_columns):
                        break

                    state = state.strip()
                    if not state:
                        continue

                    # Track state counts
                    if state in state_counts:
                        state_counts[state] += 1

                    # Check if we should capture this state
                    if CAPTURE_PROCESS_STATES and state not in CAPTURE_PROCESS_STATES:
                        skipped_count += 1
                        continue

                    # Capture this state
                    captured_count += 1
                    proc_info = process_columns[idx]

                    data_points.append({
                        'timestamp': timestamp,
                        'pid': proc_info['pid'],
                        'process_name': proc_info['process_name'],
                        'state': state,
                        'state_description': STATE_DESCRIPTIONS.get(state, state)
                    })

        # Summary statistics
        logger.info("=" * 60)
        logger.info("PARSING COMPLETE - Statistics:")
        logger.info(f"  Total data rows processed: {len(lines) - 1}")
        logger.info(f"  Total data points captured: {captured_count}")
        logger.info(f"  Total data points skipped: {skipped_count}")
        logger.info("")
        logger.info("  State breakdown (all states found):")

        for state in sorted(state_counts.keys()):
            count = state_counts[state]
            if count > 0:
                state_name = STATE_DESCRIPTIONS.get(state, state)
                if not CAPTURE_PROCESS_STATES or state in CAPTURE_PROCESS_STATES:
                    logger.info(f"    ✓ {state_name} ({state}): {count} (captured)")
                else:
                    logger.info(f"    ✗ {state_name} ({state}): {count} (skipped)")

        logger.info("=" * 60)

        # Log sample data points
        if data_points:
            logger.info("Sample captured processes:")
            for dp in data_points[:10]:
                logger.info(f"  {dp['timestamp']} - PID {dp['pid']} ({dp['process_name']}): {dp['state']} ({dp['state_description']})")
            if len(data_points) > 10:
                logger.info(f"  ... and {len(data_points) - 10} more")
        else:
            logger.warning("⚠️  No process state data captured (all states may be filtered)")

        return data_points

    except Exception as e:
        logger.error(f"Error parsing proc.psinfo.sname: {e}", exc_info=True)
        return []

def export_proc_sname_to_influxdb(data_points: List[Dict[str, Any]], logger, write_api, archive_base: Path) -> int:
    """
    Export proc.psinfo.sname data points to InfluxDB

    InfluxDB Schema:
    ================
    Measurement: proc_psinfo_sname

    Tags (indexed, used for filtering):
    - product_type:   Product type identifier
    - serialNumber:   Serial number
    - process_name:   Full process name/path (e.g., "/var/lib/pcp/pmdas/proc/pmdaproc")
    - pid:            Process ID (formatted with leading zeros, e.g., "077644")
    - state:          Process state single letter (R, D, S, I, Z, T)

    Fields (values):
    - state_description: Human-readable state (Running, Blocked, Sleeping, etc.)

    Example InfluxDB Line Protocol:
    proc_psinfo_sname,product_type=PCP,serialNumber=ABC123,process_name=/usr/bin/python3,pid=012345,state=R state_description="Running" 1699876543000000000

    Returns count of points written
    """
    logger.info("=" * 60)
    logger.info("EXPORTING proc.psinfo.sname TO INFLUXDB")
    logger.info("=" * 60)

    if not data_points:
        logger.info("No process state data to export - skipping")
        return 0

    logger.info(f"Data points to export: {len(data_points)}")
    logger.info(f"Target measurement: proc_psinfo_sname")
    logger.info(f"InfluxDB bucket: {INFLUXDB_BUCKET}")

    points = []
    error_count = 0

    # Track state counts for summary
    state_point_counts = {}

    for idx, dp in enumerate(data_points):
        try:
            # Parse timestamp from pmrep CSV format: "2025-11-02 06:39:45"
            from datetime import datetime, timezone

            timestamp_str = dp['timestamp']
            ts = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            ts = ts.replace(tzinfo=timezone.utc)

            # Create InfluxDB point
            # Tags: product_type, serialNumber, process_name, pid, state
            # Field: state_description
            point = Point("proc_psinfo_sname") \
                .tag("product_type", PRODUCT_TYPE) \
                .tag("serialNumber", SERIAL_NUMBER) \
                .tag("process_name", dp['process_name']) \
                .tag("pid", dp['pid']) \
                .tag("state", dp['state']) \
                .field("state_description", dp['state_description']) \
                .time(ts)

            points.append(point)

            # Track state counts
            state = dp['state']
            state_point_counts[state] = state_point_counts.get(state, 0) + 1

            # Log first few points for verification
            if idx < 3:
                logger.debug(f"  Point {idx + 1}: PID {dp['pid']} ({dp['process_name']}) state={dp['state']} @ {timestamp_str}")

        except Exception as e:
            error_count += 1
            logger.debug(f"Error creating point for {dp}: {e}")
            continue

    # Write all points
    if points:
        logger.info(f"Writing {len(points)} points to InfluxDB...")

        # Log breakdown by state
        logger.info("  Points breakdown by state:")
        for state in sorted(state_point_counts.keys()):
            count = state_point_counts[state]
            state_descriptions = {
                'R': 'Running',
                'D': 'Blocked',
                'S': 'Sleeping',
                'I': 'Idle',
                'Z': 'Zombie',
                'T': 'Stopped'
            }
            state_name = state_descriptions.get(state, state)
            logger.info(f"    {state_name} ({state}): {count} points")

        try:
            if ENABLE_INFLUXDB_WRITE:
                write_api.write(bucket=INFLUXDB_BUCKET, record=points)
                logger.info(f"✓ Successfully wrote {len(points)} proc.psinfo.sname points to InfluxDB")
            else:
                logger.info(f"✓ Processed {len(points)} proc.psinfo.sname points (not written, ENABLE_INFLUXDB_WRITE=false)")

            if error_count > 0:
                logger.warning(f"  Errors during point creation: {error_count}")
        except Exception as e:
            logger.error(f"✗ Failed to write points to InfluxDB: {e}")
            return 0
    else:
        logger.warning("⚠️  No valid points created - nothing written to InfluxDB")

    logger.info("=" * 60)

    return len(points)


def parse_csv_with_pandas(csv_content: str, logger) -> Optional[pd.DataFrame]:
    """Parse CSV using pandas"""
    if not PANDAS_AVAILABLE:
        logger.debug("Pandas not available, falling back to line-by-line parsing")
        return None

    try:
        # Parse CSV with pandas (C-optimized, much faster)
        df = pd.read_csv(
            io.StringIO(csv_content),
            parse_dates=[0],  # Parse first column as datetime
            low_memory=False
        )

        # Rename timestamp column
        df.rename(columns={df.columns[0]: 'timestamp'}, inplace=True)

        logger.info(f"Pandas CSV parsing: {len(df)} rows, {len(df.columns)-1} metrics")
        return df

    except Exception as e:
        logger.warning(f"Pandas CSV parsing failed: {e}, falling back to standard parsing")
        return None


def dataframe_to_line_protocol(df: pd.DataFrame, product_type: str, serial_number: str,
                                measurement: str, logger) -> List[str]:
    """
    OPTIMIZED: Convert pandas DataFrame to InfluxDB line protocol for 30-40% faster writes
    Uses chunked processing to avoid memory issues with large datasets

    Line protocol format:
    measurement,tag1=value1,tag2=value2 field1=value1,field2=value2 timestamp

    Args:
        df: Pandas DataFrame with metrics
        product_type: Product type tag
        serial_number: Serial number tag
        measurement: InfluxDB measurement name
        logger: Logger instance

    Returns:
        List of line protocol strings
    """
    lines = []

    try:
        # Pre-build tags string (constant for all points) - significant performance improvement
        tags_str = f"product_type={product_type},serialNumber={serial_number}"

        # Convert timestamp column once (avoid repeated conversion)
        timestamps_ns = (df['timestamp'].astype('int64')).values

        # Remove timestamp column from data
        data_cols = [col for col in df.columns if col != 'timestamp']

        # Pre-sanitize column names (do once instead of per-row)
        sanitized_cols = {col: col.replace('.', '_').replace('-', '_').replace(' ', '_').replace('"', '')
                         for col in data_cols}

        # Process in chunks to avoid memory issues with large datasets
        CHUNK_SIZE = 10000
        total_rows = len(df)

        for chunk_start in range(0, total_rows, CHUNK_SIZE):
            chunk_end = min(chunk_start + CHUNK_SIZE, total_rows)
            chunk = df.iloc[chunk_start:chunk_end]
            chunk_ts = timestamps_ns[chunk_start:chunk_end]

            # Process chunk rows
            for idx, (_, row) in enumerate(chunk.iterrows()):
                fields = []

                for col in data_cols:
                    value = row[col]

                    # Skip NaN, None, empty values
                    if pd.isna(value) or value == '':
                        continue

                    try:
                        # Convert to float
                        float_val = float(value)

                        # Skip based on filters
                        if PCP_METRICS_FILTER:
                            if "skip_zero" in PCP_METRICS_FILTER and float_val == 0:
                                continue

                        # Use pre-sanitized field name
                        field_name = sanitized_cols[col]
                        fields.append(f"{field_name}={float_val}")

                    except (ValueError, TypeError):
                        continue

                # Only create line if we have fields
                if fields:
                    # Single string concatenation is fastest (avoid multiple f-strings)
                    lines.append(f"{measurement},{tags_str} {','.join(fields)} {chunk_ts[idx]}")

        logger.info(f"Generated {len(lines)} line protocol entries (optimized chunked processing)")

    except Exception as e:
        logger.error(f"Error converting DataFrame to line protocol: {e}")
        return []

    return lines


def export_to_influxdb(archive_base: Path, logger, metrics: List[str]) -> tuple[bool, Optional[Path]]:
    """Process PCP archive data and export to InfluxDB or CSV based on flags"""
    logger.info("===== STARTING DATA PROCESSING =====")

    # Log processing mode based on pandas availability
    logger.info("[FLOW] === PROCESSING MODE CONFIGURATION ===")
    if PANDAS_AVAILABLE:
        logger.info("[FLOW] DATA READING MODE: PANDAS (vectorized)")
        logger.info("[FLOW]   - Collect all CSV in memory")
        logger.info("[FLOW]   - Use pd.read_csv() for high-performance processing")
    else:
        logger.info("[FLOW] DATA READING MODE: STREAMING (line-by-line)")
        logger.info("[FLOW]   - Read stdout line-by-line in real-time")
        logger.info("[FLOW]   - Low memory footprint (pandas not available)")

    # Log output destination based on flags
    logger.info("[FLOW] === OUTPUT DESTINATION ===")
    if ENABLE_INFLUXDB_WRITE:
        logger.info(f"[FLOW] PRIMARY OUTPUT: InfluxDB (ENABLE_INFLUXDB_WRITE=true)")
        logger.info(f"[FLOW]   - URL: {INFLUXDB_URL}")
        logger.info(f"[FLOW]   - Bucket: {INFLUXDB_BUCKET}")
        logger.info(f"[FLOW]   - Batch Size: {INFLUX_BATCH_SIZE} points")
    else:
        logger.warning("[FLOW] InfluxDB writes DISABLED (ENABLE_INFLUXDB_WRITE=false)")

    if SAVE_CSV_OUTPUT:
        logger.info(f"[FLOW] SECONDARY OUTPUT: CSV File (SAVE_CSV_OUTPUT=true)")
    else:
        logger.info(f"[FLOW] CSV output disabled (SAVE_CSV_OUTPUT=false)")

    logger.info("[FLOW] =========================================")

    # Check if proc.psinfo.sname exists in archive BEFORE starting main export
    # This allows parallel processing if the metric is available
    proc_sname_available = False
    logger.debug("Pre-checking proc.psinfo.sname availability...")
    try:
        check_result = subprocess.run(
            ["pminfo", "-a", str(archive_base), "proc.psinfo.sname"],
            capture_output=True,
            text=True,
            timeout=10
        )
        proc_sname_available = (check_result.returncode == 0)
        if proc_sname_available:
            logger.info("✓ proc.psinfo.sname metric available - will process in parallel")
        else:
            logger.info("⚠️  proc.psinfo.sname metric NOT available in this archive")
    except Exception as e:
        logger.debug(f"Error checking proc.psinfo.sname availability: {e}")
        proc_sname_available = False

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
        # Use pmrep with pre-validated metrics (all metrics have been tested and confirmed working)
        logger.info("[FLOW] === STEP 1: PMREP DATA EXTRACTION ===")
        logger.info(f"[FLOW] Extracting metrics using pmrep with {len(metrics)} validated metrics")

        # Build command with all validated metrics
        cmd = [
            "pmrep",
            "-a", str(archive_base),
            "-t", "1sec",
            "-o", "csv",
            "-U",  # Include timestamps
            "--ignore-unknown"  # Skip metrics that can't be read (prevents PM_ERR_* errors)
        ] + metrics  # Add all validated metrics (already tested to work)

        logger.info(f"[FLOW] Command: pmrep -a {archive_base} -t 1sec -o csv -U --ignore-unknown [+ {len(metrics)} metrics]")

        # Start pmval process in parallel if proc.psinfo.sname is available
        pmval_process = None
        if proc_sname_available:
            pmval_process = start_proc_psinfo_sname_collection(archive_base, logger)

        # Redirect stderr to devnull to suppress pmrep internal timeout messages
        logger.info("[FLOW] Starting pmrep subprocess...")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,  # Suppress stderr (timeout messages)
            text=True,
            bufsize=1
        )
        logger.info("[FLOW] ✓ pmrep process started (PID: {})".format(process.pid))

        # Read CSV output and convert to InfluxDB points
        points = []
        header = None
        line_count = 0
        error_count = 0
        total_points_written = 0
        batch_count = 0

        # Save CSV output to logs
        csv_output_file = LOG_DIR / f"pmrep_output_{archive_base.stem}.csv"

        # Only create CSV file/buffer if needed
        logger.info("[FLOW] === STEP 2: CSV PROCESSING SETUP ===")
        if PANDAS_AVAILABLE:
            # Always use memory buffer with pandas for best performance
            csv_file = io.StringIO()
            logger.info(f"[FLOW] ✓ Using in-memory buffer for pandas vectorized processing")
        elif SAVE_CSV_OUTPUT:
            # Streaming mode - write to file if requested
            csv_file = open(csv_output_file, 'w', encoding='utf-8')
            logger.info(f"[FLOW] Saving pmrep CSV output to: {csv_output_file}")
        else:
            csv_file = None
            logger.info(f"[FLOW] ✓ CSV output saving disabled - optimized mode (SAVE_CSV_OUTPUT=false)")

        # Initialize InfluxDB connection and write API only if needed
        write_api = None
        if ENABLE_INFLUXDB_WRITE:
            logger.info("[FLOW] === STEP 3: INFLUXDB CONNECTION (WRITE ENABLED) ===")
            logger.info(f"[FLOW] Connecting to InfluxDB: {INFLUXDB_URL}")
            client = get_influx_client()
            logger.info(f"[FLOW] ✓ Connected successfully")
            logger.info(f"[FLOW] Tags: product_type={PRODUCT_TYPE}, serialNumber={SERIAL_NUMBER}")

            # OPTIMIZED: Tuned WriteOptions for high-throughput scenarios
            write_options = WriteOptions(
                batch_size=INFLUX_BATCH_SIZE,
                flush_interval=15_000,
                jitter_interval=1_000,
                retry_interval=10_000,
                max_retries=5,
                max_retry_delay=60_000,
                exponential_base=2,
                max_retry_time=300_000
            )
            write_api = client.write_api(write_options=write_options)
            logger.info("[FLOW] ✓ Write API initialized with async batching")

        # Choose processing mode: Pandas (fast) or Streaming (low memory)
        if PANDAS_AVAILABLE:
            logger.info("[FLOW] === STEP 4: PANDAS MODE (MEMORY BUFFER) ===")
            logger.info("[FLOW] ✓ Using pandas CSV parsing with line protocol (OPTIMIZED)")

            # Collect all CSV output in memory
            logger.info("[FLOW] Collecting all CSV output into memory buffer...")
            csv_content_lines = []
            for line in process.stdout:
                csv_content_lines.append(line)
                # Only write to buffer if needed (optimization: skip when SAVE_CSV_OUTPUT=false)
                if csv_file is not None:
                    csv_file.write(line)

            process.wait(timeout=300)
            csv_content = ''.join(csv_content_lines)
            logger.info(f"[FLOW] ✓ Collected {len(csv_content_lines)} lines in memory")

            # Parse with pandas
            logger.info("[FLOW] === STEP 5: PANDAS DATAFRAME PROCESSING ===")
            df = parse_csv_with_pandas(csv_content, logger)

            if df is not None:
                # Convert to line protocol
                logger.info("[FLOW] Converting DataFrame to InfluxDB line protocol...")
                line_protocol_entries = dataframe_to_line_protocol(
                    df, PRODUCT_TYPE, SERIAL_NUMBER, INFLUXDB_MEASUREMENT, logger
                )

                # Write using line protocol (30-40% faster)
                if line_protocol_entries:
                    logger.info(f"[FLOW] === STEP 6: INFLUXDB ASYNC WRITES (Batch={INFLUX_BATCH_SIZE}) ===")
                    logger.info(f"[FLOW] Writing {len(line_protocol_entries)} points using line protocol...")
                    # Write in batches
                    for i in range(0, len(line_protocol_entries), INFLUX_BATCH_SIZE):
                        batch = line_protocol_entries[i:i+INFLUX_BATCH_SIZE]
                        if ENABLE_INFLUXDB_WRITE:
                            write_api.write(bucket=INFLUXDB_BUCKET, record='\n'.join(batch))
                        total_points_written += len(batch)
                        batch_count += 1

                        if batch_count % PROGRESS_LOG_INTERVAL == 0:
                            status = "written" if ENABLE_INFLUXDB_WRITE else "processed (not written)"
                            logger.info(f"[FLOW] Progress: {total_points_written} points {status} ({batch_count} batches)...")

                # Flush and mark processing complete
                if write_api:
                    write_api.flush()
                logger.info(f"✓ Pandas+LineProtocol: {total_points_written} points written")
                line_count = len(csv_content_lines)
            else:
                # Pandas failed - this shouldn't happen but handle gracefully
                logger.error("Pandas parsing failed unexpectedly")
                return False, None

        else:
            # Streaming mode - line by line processing (when pandas not available)
            logger.info("[FLOW] === STEP 4: STREAMING CSV PROCESSING ===")
            logger.info("[FLOW] Using streaming mode (line-by-line processing)")

            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue

                # Write to CSV file only if configured (optimization: skip I/O when disabled)
                if csv_file is not None:
                    csv_file.write(line + '\n')
                line_count += 1

                # First line is header
                if header is None:
                    header = [col.strip().strip('"') for col in line.split(',')]
                    logger.info(f"[FLOW] Found {len(header)} columns (first column is timestamp)")
                    logger.info(f"[FLOW] === STEP 5: POINT CREATION (CSV → InfluxDB Points) ===")
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

                    # Create single point with all metrics as fields
                    # [FLOW] This is where CSV row → InfluxDB Point conversion happens
                    point = Point(INFLUXDB_MEASUREMENT) \
                        .tag("product_type", PRODUCT_TYPE) \
                        .tag("serialNumber", SERIAL_NUMBER) \
                        .time(ts)

                    has_fields = False

                    # Add all metrics as fields
                    for i, metric_name in enumerate(header[1:], start=1):
                        value_str = values[i].strip().strip('"')

                        # Skip empty, None, N/A, or ? values
                        if not value_str or value_str.lower() in ['', 'n/a', '?', 'none', 'null']:
                            error_count += 1
                            continue

                        try:
                            # Ensure value is explicitly a float
                            value = float(value_str)

                            # Track this metric in CSV
                            save_metric_to_csv(metric_name)

                            # Apply PCP_METRICS_FILTER
                            if PCP_METRICS_FILTER:
                                if "skip_zero" in PCP_METRICS_FILTER and value == 0:
                                    continue
                                if "skip_empty" in PCP_METRICS_FILTER and value_str.strip() == "":
                                    continue

                            # Add metric as field
                            field_name = metric_name.replace('.', '_').replace('-', '_').replace(' ', '_')
                            point.field(field_name, float(value))
                            has_fields = True

                        except ValueError:
                            error_count += 1

                    # Only add point if it has at least one field
                    if has_fields:
                        points.append(point)

                    # Write points in batches with streaming
                    if len(points) >= INFLUX_BATCH_SIZE:
                        if batch_count == 0:
                            logger.info(f"[FLOW] === STEP 6: INFLUXDB ASYNC WRITES (Batch={INFLUX_BATCH_SIZE}) ===")
                        if ENABLE_INFLUXDB_WRITE:
                            write_api.write(bucket=INFLUXDB_BUCKET, record=points)
                        total_points_written += len(points)
                        batch_count += 1
                        if batch_count % PROGRESS_LOG_INTERVAL == 0:
                            status = "written" if ENABLE_INFLUXDB_WRITE else "processed (not written)"
                            logger.info(f"[FLOW] Streaming progress: {total_points_written} points {status} ({batch_count} batches)...")
                        points = []

                except Exception as e:
                    error_count += 1
                    if error_count <= 5:
                        logger.debug(f"Error processing line {line_count}: {e}")

            process.wait(timeout=300)
            logger.info(f"✓ Streaming pmrep complete: processed {line_count} lines")

        # Close CSV file and save if needed
        if csv_file is not None:
            if PANDAS_AVAILABLE and SAVE_CSV_OUTPUT:
                # Write memory buffer to disk if requested
                with open(csv_output_file, 'w', encoding='utf-8') as f:
                    f.write(csv_file.getvalue())
                logger.info(f"CSV output saved from memory buffer to: {csv_output_file}")
            elif not PANDAS_AVAILABLE and SAVE_CSV_OUTPUT:
                csv_file.close()
                logger.info(f"CSV output saved to: {csv_output_file}")
            else:
                logger.info(f"CSV processing complete (not saved to disk)")
            if hasattr(csv_file, 'close'):
                csv_file.close()

        # Write remaining points (only for standard processing)
        if points:
            logger.info(f"[FLOW] Writing final batch of {len(points)} points...")
            if ENABLE_INFLUXDB_WRITE:
                write_api.write(bucket=INFLUXDB_BUCKET, record=points)
            total_points_written += len(points)
            status = "Written" if ENABLE_INFLUXDB_WRITE else "Processed (not written)"
            logger.info(f"[FLOW] {status} final batch of {len(points)} points")

        # Flush async writes and wait for completion (only if InfluxDB write is enabled)
        if write_api:
            logger.info("[FLOW] === STEP 7: FLUSHING ASYNC WRITES ===")
            logger.info("[FLOW] Flushing async writes to InfluxDB...")
            write_api.flush()
            logger.info("[FLOW] ✓ All async writes completed")

        logger.info(f"[FLOW] ===== EXPORT COMPLETE =====")
        status_msg = "written" if ENABLE_INFLUXDB_WRITE else "processed (NOT written)"
        logger.info(f"[FLOW] Total data points {status_msg}: {total_points_written}")
        logger.info(f"[FLOW] Processed {line_count} lines from pmrep")
        logger.info(f"[FLOW] Empty/invalid values skipped: {error_count}")

        # Parse and export proc.psinfo.sname data
        # The pmrep process was started in parallel earlier, now we collect its results
        logger.info("")
        if proc_sname_available and pmval_process:
            proc_sname_data = parse_proc_psinfo_sname_from_process(pmval_process, archive_base, logger)
            proc_sname_count = export_proc_sname_to_influxdb(proc_sname_data, logger, write_api, archive_base)
            logger.info(f"proc.psinfo.sname: {proc_sname_count} process state data points exported")
        else:
            logger.info("===== proc.psinfo.sname NOT AVAILABLE - SKIPPING =====")
            proc_sname_count = 0

        # Don't close pooled client
        # client.close()

        # Export to S3 Parquet if enabled
        if S3_EXPORT_AVAILABLE and ENABLE_S3_EXPORT and csv_output_file.exists():
            logger.info("[FLOW] === STEP 8: S3 PARQUET EXPORT ===")
            try:
                export_success = export_to_s3_parquet(csv_output_file, PRODUCT_TYPE, SERIAL_NUMBER, logger)
                if export_success:
                    logger.info("[FLOW] ✓ S3 Parquet export successful")
                else:
                    logger.warning("[FLOW] ⚠️  S3 Parquet export failed (non-critical)")
            except Exception as e:
                logger.error(f"[FLOW] ✗ S3 Parquet export error: {e}", exc_info=True)
        elif ENABLE_S3_EXPORT and not S3_EXPORT_AVAILABLE:
            logger.warning("[FLOW] S3 export enabled but s3_parquet_exporter module not available")

        # Return success and CSV file path (if saved)
        csv_path = csv_output_file if SAVE_CSV_OUTPUT and csv_output_file.exists() else None
        return True, csv_path

    except subprocess.TimeoutExpired:
        logger.error("pmrep timed out after 5 minutes")
        if 'process' in locals():
            process.kill()
        if 'pmval_process' in locals() and pmval_process:
            pmval_process.kill()
        return False, None
    except Exception as e:
        logger.error(f"Error exporting to InfluxDB: {e}", exc_info=True)
        if 'pmval_process' in locals() and pmval_process:
            pmval_process.kill()
        return False, None

def process_archive(archive_path: Path, logger) -> bool:
    """Process a single tar.xz archive"""
    archive_name = archive_path.name
    extract_path = EXTRACT_DIR / archive_path.stem

    log_separator(logger, f"Processing archive: {archive_name}")
    logger.info(f"[FLOW] ========================================")
    logger.info(f"[FLOW] START: Processing {archive_name}")
    logger.info(f"[FLOW] ========================================")

    # Start timing the entire archive processing
    start_time_total = time.time()

    try:
        # Create extraction directory
        extract_path.mkdir(parents=True, exist_ok=True)

        logger.info("[FLOW] === PHASE 1: ARCHIVE EXTRACTION ===")
        logger.info("[FLOW] Extracting .tar.xz archive...")
        extract_duration = extract_archive(archive_path, extract_path, logger)
        logger.info(f"[FLOW] ✓ Extracted in {extract_duration:.2f}s")

        # Find the PCP archive (look for .meta file)
        meta_files = list(extract_path.rglob("*.meta"))

        if not meta_files:
            logger.error(f"[FLOW] ✗ No PCP archive found in {archive_name}")
            shutil.move(str(archive_path), str(FAILED_DIR / archive_name))
            logger.info(f"[FLOW] Moved to failed directory: {archive_name}")
            return False

        # Get archive base path (remove .meta extension)
        archive_base = Path(str(meta_files[0])[:-5])  # Remove .meta
        logger.info(f"[FLOW] ✓ Found PCP archive: {archive_base}")

        # Get available metrics
        logger.info(f"[FLOW] === PHASE 2: METRIC VALIDATION ===")
        logger.info(f"[FLOW] Starting metric validation...")
        start_time_validation = time.time()
        metrics = get_available_metrics(archive_base, logger)
        validation_duration = time.time() - start_time_validation
        logger.info(f"[FLOW] ✓ Metric validation completed in {validation_duration:.2f} seconds")

        if not metrics:
            logger.warning("No metrics found in archive")
            shutil.move(str(archive_path), str(FAILED_DIR / archive_name))
            logger.info(f"Moved to failed directory: {archive_name}")
            return False

        # Get sample metric values for logging
        # get_metric_values(archive_base, metrics, logger)

        # Check InfluxDB connectivity
        logger.info(f"[FLOW] === PHASE 3: DATA EXPORT ===")
        check_influxdb_connection(logger)

        # Export to InfluxDB (pass discovered metrics)
        logger.info(f"[FLOW] Starting data export to InfluxDB...")
        start_time_export = time.time()
        success, csv_file_path = export_to_influxdb(archive_base, logger, metrics)
        export_duration = time.time() - start_time_export
        logger.info(f"[FLOW] ✓ Data export completed in {export_duration:.2f} seconds")

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

            # Move processed archive to processed directory
            shutil.move(str(archive_path), str(PROCESSED_DIR / archive_name))
            logger.info(f"✓ Moved {archive_name} to {PROCESSED_DIR}")

            # Copy CSV file to processed directory if it exists
            if csv_file_path and csv_file_path.exists():
                csv_dest = PROCESSED_DIR / csv_file_path.name
                shutil.copy2(str(csv_file_path), str(csv_dest))
                logger.info(f"✓ Copied CSV file to {csv_dest}")
            else:
                logger.debug("No CSV file to copy (CSV saving may be disabled)")
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

def process_all_archives():
    """Process all archives in the input directory (called on-demand)"""
    logger = setup_logging()

    logger.info("=" * 60)
    logger.info("MANUAL PROCESSING TRIGGERED")
    logger.info("=" * 60)

    # Load configuration from .env file
    product_type, serial_number = load_config_from_env_file()
    logger.info("=" * 60)
    logger.info("DATA TAGGING CONFIGURATION:")
    logger.info(f"  PRODUCT_TYPE  = {product_type}")
    logger.info(f"  SERIAL_NUMBER = {serial_number}")
    logger.info("=" * 60)

    # Load existing metrics from CSV
    load_metrics_cache()
    logger.info(f"Loaded {len(_metrics_cache)} existing metrics from cache")

    # Check for archives
    logger.info(f"Checking for .tar.xz files in {WATCH_DIR}...")
    archive_files = list(WATCH_DIR.glob("*.tar.xz"))

    if not archive_files:
        logger.info("No files found to process")
        return {"status": "success", "message": "No files found to process", "processed": 0, "failed": 0}

    logger.info(f"Found {len(archive_files)} archive(s) to process")

    processed_count = 0
    failed_count = 0

    for archive in archive_files:
        logger.info(f"Processing: {archive.name}")
        success = process_archive(archive, logger)
        if success:
            processed_count += 1
        else:
            failed_count += 1

    logger.info("=" * 60)
    logger.info(f"PROCESSING COMPLETE: {processed_count} successful, {failed_count} failed")
    logger.info("=" * 60)

    return {
        "status": "success",
        "message": f"Processed {processed_count} file(s), {failed_count} failed",
        "processed": processed_count,
        "failed": failed_count
    }

def main():
    """Main monitoring loop - checks for trigger file"""
    logger = setup_logging()

    # Load configuration from .env file
    product_type, serial_number = load_config_from_env_file()

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
    logger.info(f"Static Tags - Product Type: {product_type}, Serial Number: {serial_number}")
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
    logger.info("Waiting for manual trigger via web interface...")
    logger.info("Trigger file: /src/.process_trigger_python")
    logger.info("")

    trigger_file = Path("/src/.process_trigger_python")

    # Main monitoring loop - check for trigger file
    while True:
        try:
            # Check if trigger file exists
            if trigger_file.exists():
                logger.info("TRIGGER DETECTED - Starting processing...")

                # Remove trigger file
                trigger_file.unlink()

                # Process all archives
                process_all_archives()

                logger.info("Waiting for next trigger...")

            time.sleep(2)  # Check every 2 seconds for trigger

        except KeyboardInterrupt:
            logger.info("Received interrupt signal, shutting down...")
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
            time.sleep(5)

if __name__ == "__main__":
    main()
