use anyhow::{Context, Result};
use chrono::{DateTime, NaiveDateTime, Utc};
use csv::{Reader, Writer};
use influxdb::{Client, InfluxDbWriteable, Timestamp};
use log::{error, info, warn};
use std::collections::{HashMap, HashSet};
use std::env;
use std::fs::{self, File};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

/// Configuration loaded from environment variables
#[derive(Debug, Clone)]
struct Config {
    watch_dir: PathBuf,
    extract_dir: PathBuf,
    processed_dir: PathBuf,
    failed_dir: PathBuf,
    log_dir: PathBuf,
    metrics_csv: PathBuf,
    validated_metrics_cache: PathBuf,

    influxdb_url: String,
    influxdb_token: String,
    influxdb_org: String,
    influxdb_bucket: String,
    influxdb_measurement: String,

    product_type: String,
    serial_number: String,

    pcp_metrics_filter: String,
    validation_batch_size: usize,
    influx_batch_size: usize,
    progress_log_interval: usize,
    skip_validation: bool,
    force_revalidate: bool,

    enable_process_metrics: bool,
    enable_disk_metrics: bool,
    enable_file_metrics: bool,
    enable_memory_metrics: bool,
    enable_network_metrics: bool,
    enable_kernel_metrics: bool,
    enable_swap_metrics: bool,
    enable_nfs_metrics: bool,
}

impl Config {
    fn from_env() -> Result<Self> {
        let log_dir = PathBuf::from(env::var("LOG_DIR").unwrap_or_else(|_| "/src/logs/pcp_parser_rust".to_string()));

        Ok(Config {
            watch_dir: PathBuf::from(env::var("WATCH_DIR").unwrap_or_else(|_| "/src/input/raw".to_string())),
            extract_dir: PathBuf::from(env::var("EXTRACT_DIR").unwrap_or_else(|_| "/tmp/pcp_archives".to_string())),
            processed_dir: PathBuf::from(env::var("PROCESSED_DIR").unwrap_or_else(|_| "/src/archive/processed".to_string())),
            failed_dir: PathBuf::from(env::var("FAILED_DIR").unwrap_or_else(|_| "/src/archive/failed".to_string())),
            log_dir: log_dir.clone(),
            metrics_csv: log_dir.join("metrics_labels.csv"),
            validated_metrics_cache: log_dir.join("validated_metrics.txt"),

            influxdb_url: env::var("INFLUXDB_URL").unwrap_or_else(|_| "http://influxdb:8086".to_string()),
            influxdb_token: env::var("INFLUXDB_TOKEN").unwrap_or_default(),
            influxdb_org: env::var("INFLUXDB_ORG").unwrap_or_else(|_| "pcp-org".to_string()),
            influxdb_bucket: env::var("INFLUXDB_BUCKET").unwrap_or_else(|_| "pcp-metrics".to_string()),
            influxdb_measurement: env::var("INFLUXDB_MEASUREMENT").unwrap_or_else(|_| "pcp_metrics".to_string()),

            product_type: "SERVER1".to_string(),
            serial_number: "1234".to_string(),

            pcp_metrics_filter: env::var("PCP_METRICS_FILTER").unwrap_or_default().to_lowercase(),
            validation_batch_size: env::var("VALIDATION_BATCH_SIZE")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(100),
            influx_batch_size: env::var("INFLUX_BATCH_SIZE")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(50000),
            progress_log_interval: env::var("PROGRESS_LOG_INTERVAL")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(50),
            skip_validation: env::var("SKIP_VALIDATION")
                .map(|s| s.to_lowercase() == "true")
                .unwrap_or(false),
            force_revalidate: env::var("FORCE_REVALIDATE")
                .map(|s| s.to_lowercase() == "true")
                .unwrap_or(false),

            enable_process_metrics: env::var("ENABLE_PROCESS_METRICS")
                .map(|s| s.to_lowercase() == "true")
                .unwrap_or(false),
            enable_disk_metrics: env::var("ENABLE_DISK_METRICS")
                .map(|s| s.to_lowercase() == "true")
                .unwrap_or(true),
            enable_file_metrics: env::var("ENABLE_FILE_METRICS")
                .map(|s| s.to_lowercase() == "true")
                .unwrap_or(true),
            enable_memory_metrics: env::var("ENABLE_MEMORY_METRICS")
                .map(|s| s.to_lowercase() == "true")
                .unwrap_or(true),
            enable_network_metrics: env::var("ENABLE_NETWORK_METRICS")
                .map(|s| s.to_lowercase() == "true")
                .unwrap_or(true),
            enable_kernel_metrics: env::var("ENABLE_KERNEL_METRICS")
                .map(|s| s.to_lowercase() == "true")
                .unwrap_or(true),
            enable_swap_metrics: env::var("ENABLE_SWAP_METRICS")
                .map(|s| s.to_lowercase() == "true")
                .unwrap_or(true),
            enable_nfs_metrics: env::var("ENABLE_NFS_METRICS")
                .map(|s| s.to_lowercase() == "true")
                .unwrap_or(false),
        })
    }

    fn load_tags_from_env(&mut self) -> Result<()> {
        let env_file = Path::new("/src/.env");

        if env_file.exists() {
            let file = File::open(env_file)?;
            let reader = BufReader::new(file);

            for line in reader.lines() {
                let line = line?;
                let line = line.trim();

                if line.is_empty() || line.starts_with('#') {
                    continue;
                }

                if let Some((key, value)) = line.split_once('=') {
                    let key = key.trim();
                    let value = value.trim();

                    match key {
                        "PRODUCT_TYPE" => self.product_type = value.to_string(),
                        "SERIAL_NUMBER" => self.serial_number = value.to_string(),
                        _ => {}
                    }
                }
            }
        } else {
            // Fallback to environment variables
            if let Ok(product_type) = env::var("PRODUCT_TYPE") {
                self.product_type = product_type;
            }
            if let Ok(serial_number) = env::var("SERIAL_NUMBER") {
                self.serial_number = serial_number;
            }
        }

        Ok(())
    }
}

/// InfluxDB Point representation
#[derive(InfluxDbWriteable)]
struct MetricPoint {
    time: DateTime<Utc>,
    #[influxdb(tag)]
    product_type: String,
    #[influxdb(tag)]
    serial_number: String,
}

/// Metrics cache for CSV tracking
struct MetricsCache {
    cache: HashSet<String>,
    csv_path: PathBuf,
}

impl MetricsCache {
    fn new(csv_path: PathBuf) -> Result<Self> {
        let mut cache = HashSet::new();

        if csv_path.exists() {
            let file = File::open(&csv_path)?;
            let mut reader = Reader::from_reader(file);

            for result in reader.records() {
                if let Ok(record) = result {
                    if let Some(metric) = record.get(0) {
                        cache.insert(metric.to_string());
                    }
                }
            }
        }

        Ok(MetricsCache { cache, csv_path })
    }

    fn add_metric(&mut self, metric: &str) -> Result<()> {
        if self.cache.contains(metric) {
            return Ok(());
        }

        self.cache.insert(metric.to_string());

        let file_exists = self.csv_path.exists();
        let file = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.csv_path)?;

        let mut writer = Writer::from_writer(file);

        if !file_exists {
            writer.write_record(&["metric_name"])?;
        }

        writer.write_record(&[metric])?;
        writer.flush()?;

        Ok(())
    }
}

/// Extract .tar.xz archive
fn extract_archive(archive_path: &Path, extract_dir: &Path) -> Result<PathBuf> {
    let start = Instant::now();
    info!("Extracting archive...");

    let base_name = archive_path
        .file_stem()
        .and_then(|s| s.to_str())
        .context("Invalid archive filename")?;

    // Remove .tar from .tar.xz
    let base_name = base_name.trim_end_matches(".tar");

    let target_dir = extract_dir.join(base_name);

    // Remove existing directory if it exists
    if target_dir.exists() {
        fs::remove_dir_all(&target_dir)?;
    }

    fs::create_dir_all(&target_dir)?;

    // Extract using tar command (more reliable for PCP archives)
    let output = Command::new("tar")
        .arg("-xJf")
        .arg(archive_path)
        .arg("-C")
        .arg(&target_dir)
        .output()
        .context("Failed to execute tar command")?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(anyhow::anyhow!("Extraction failed: {}", stderr));
    }

    let elapsed = start.elapsed().as_secs_f64();
    info!("Extracted to {:?} in {:.2} seconds", target_dir, elapsed);

    Ok(target_dir)
}

/// Find PCP archive base path (looks for .meta file)
fn find_pcp_archive(extract_dir: &Path) -> Result<PathBuf> {
    for entry in fs::read_dir(extract_dir)? {
        let entry = entry?;
        let path = entry.path();

        if path.is_file() && path.extension().and_then(|s| s.to_str()) == Some("meta") {
            // Remove .meta extension to get base path
            return Ok(path.with_extension(""));
        }

        // Recursively search subdirectories
        if path.is_dir() {
            if let Ok(archive) = find_pcp_archive(&path) {
                return Ok(archive);
            }
        }
    }

    Err(anyhow::anyhow!("No PCP archive found (no .meta file)"))
}

/// Load validated metrics from cache
fn load_validated_metrics_cache(cache_path: &Path, force_revalidate: bool) -> Result<Option<Vec<String>>> {
    if force_revalidate {
        info!("FORCE_REVALIDATE=true, skipping cache");
        return Ok(None);
    }

    if !cache_path.exists() {
        info!("No validation cache found, will validate metrics");
        return Ok(None);
    }

    let file = File::open(cache_path)?;
    let reader = BufReader::new(file);

    let metrics: Vec<String> = reader
        .lines()
        .filter_map(|line| line.ok())
        .map(|line| line.trim().to_string())
        .filter(|line| !line.is_empty())
        .collect();

    info!("Loaded {} validated metrics from cache", metrics.len());
    Ok(Some(metrics))
}

/// Save validated metrics to cache
fn save_validated_metrics_cache(metrics: &[String], cache_path: &Path) -> Result<()> {
    let file = File::create(cache_path)?;
    let mut writer = BufWriter::new(file);

    for metric in metrics {
        writeln!(writer, "{}", metric)?;
    }

    writer.flush()?;
    info!("Saved {} validated metrics to cache", metrics.len());

    Ok(())
}

/// Discover and validate metrics from PCP archive
fn discover_and_validate_metrics(archive_base: &Path, config: &Config) -> Result<Vec<String>> {
    info!("Discovering metrics in archive...");

    // Get all metrics using pminfo
    let output = Command::new("pminfo")
        .arg("-a")
        .arg(archive_base)
        .output()
        .context("Failed to execute pminfo")?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(anyhow::anyhow!("pminfo failed: {}", stderr));
    }

    let all_metrics: Vec<String> = String::from_utf8_lossy(&output.stdout)
        .lines()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect();

    // If SKIP_VALIDATION is enabled, skip validation
    if config.skip_validation {
        warn!(
            "WARNING: SKIP_VALIDATION=true: Using all {} metrics WITHOUT validation (may cause errors!)",
            all_metrics.len()
        );
        return Ok(apply_category_filters(&all_metrics, config));
    }

    info!("Found {} total metrics, validating each one...", all_metrics.len());

    let mut valid_metrics = Vec::new();
    let mut invalid_count = 0;
    let batch_size = config.validation_batch_size;

    // Test metrics in batches
    for (i, batch) in all_metrics.chunks(batch_size).enumerate() {
        let mut args = vec![
            "-a".to_string(),
            archive_base.to_str().unwrap().to_string(),
            "-s".to_string(),
            "1".to_string(),
            "-o".to_string(),
            "csv".to_string(),
            "--ignore-unknown".to_string(),
        ];

        args.extend(batch.iter().map(|s| s.to_string()));

        let output = Command::new("pmrep")
            .args(&args)
            .output()
            .context("Failed to execute pmrep")?;

        // If batch succeeds, all metrics are valid
        if output.status.success() && !output.stdout.is_empty() {
            valid_metrics.extend_from_slice(batch);
        } else {
            // Batch failed, test each metric individually
            for metric in batch {
                let output = Command::new("pmrep")
                    .args(&[
                        "-a",
                        archive_base.to_str().unwrap(),
                        "-s",
                        "1",
                        "-o",
                        "csv",
                        "--ignore-unknown",
                        metric,
                    ])
                    .output()
                    .context("Failed to execute pmrep")?;

                if output.status.success() && !output.stdout.is_empty() {
                    valid_metrics.push(metric.clone());
                } else {
                    invalid_count += 1;
                }
            }
        }

        // Progress logging
        if (i + 1) * batch_size % 200 == 0 {
            info!("Validated {}/{} metrics...", (i + 1) * batch_size, all_metrics.len());
        }
    }

    info!(
        "Found {} valid metrics (filtered out {} invalid/derived metrics)",
        valid_metrics.len(),
        invalid_count
    );

    // Apply category filters
    let filtered = apply_category_filters(&valid_metrics, config);

    Ok(filtered)
}

/// Apply category filters to metrics
fn apply_category_filters(metrics: &[String], config: &Config) -> Vec<String> {
    let original_count = metrics.len();
    let mut filtered_metrics = Vec::new();
    let mut filter_stats: HashMap<String, usize> = HashMap::new();

    for metric in metrics {
        // Check each category filter
        if metric.starts_with("proc.") && !config.enable_process_metrics {
            *filter_stats.entry("proc".to_string()).or_insert(0) += 1;
            continue;
        }
        if metric.starts_with("disk.") && !config.enable_disk_metrics {
            *filter_stats.entry("disk".to_string()).or_insert(0) += 1;
            continue;
        }
        if (metric.starts_with("vfs.") || metric.starts_with("filesys.")) && !config.enable_file_metrics {
            *filter_stats.entry("file".to_string()).or_insert(0) += 1;
            continue;
        }
        if metric.starts_with("mem.") && !config.enable_memory_metrics {
            *filter_stats.entry("mem".to_string()).or_insert(0) += 1;
            continue;
        }
        if metric.starts_with("network.") && !config.enable_network_metrics {
            *filter_stats.entry("network".to_string()).or_insert(0) += 1;
            continue;
        }
        if metric.starts_with("kernel.") && !config.enable_kernel_metrics {
            *filter_stats.entry("kernel".to_string()).or_insert(0) += 1;
            continue;
        }
        if metric.starts_with("swap.") && !config.enable_swap_metrics {
            *filter_stats.entry("swap".to_string()).or_insert(0) += 1;
            continue;
        }
        if metric.starts_with("nfs.") && !config.enable_nfs_metrics {
            *filter_stats.entry("nfs".to_string()).or_insert(0) += 1;
            continue;
        }

        filtered_metrics.push(metric.clone());
    }

    // Log filtering results
    if !filter_stats.is_empty() {
        let total_filtered: usize = filter_stats.values().sum();
        info!("Metric filtering: removed {} metrics by category:", total_filtered);
        for (category, count) in &filter_stats {
            info!("  - {}: {} metrics filtered", category, count);
        }
        info!(
            "Remaining metrics: {} (reduced from {})",
            filtered_metrics.len(),
            original_count
        );
    } else {
        info!("No category filters applied, using all {} valid metrics", filtered_metrics.len());
    }

    // Log sample metrics
    info!("Sample valid metrics to export:");
    for metric in filtered_metrics.iter().take(10) {
        info!("  - {}", metric);
    }
    if filtered_metrics.len() > 10 {
        info!("  ... and {} more", filtered_metrics.len() - 10);
    }

    filtered_metrics
}

/// Check if value should be skipped based on filter
fn should_skip_value(value: &str, filter: &str) -> bool {
    for f in filter.split(',') {
        let f = f.trim();
        match f {
            "skip_zero" if value == "0" || value == "0.0" => return true,
            "skip_empty" if value.is_empty() => return true,
            "skip_none" if matches!(value.to_lowercase().as_str(), "none" | "null" | "n/a") => return true,
            _ => {}
        }
    }
    false
}

/// Sanitize field name (replace dots, dashes, spaces with underscores)
fn sanitize_field_name(name: &str) -> String {
    name.replace('.', "_").replace('-', "_").replace(' ', "_")
}

/// Export to InfluxDB using async batched writes
async fn export_to_influxdb(
    archive_base: &Path,
    archive_name: &str,
    metrics: &[String],
    config: &Config,
    metrics_cache: &mut MetricsCache,
) -> Result<usize> {
    info!("{}", "=".repeat(60));
    info!("STARTING EXPORT TO INFLUXDB");
    info!("{}", "=".repeat(60));
    info!("Using Rust InfluxDB client");

    if !config.pcp_metrics_filter.is_empty() {
        info!("Value filtering ENABLED: {}", config.pcp_metrics_filter);
    } else {
        info!("Value filtering DISABLED: all values will be exported");
    }

    info!("Connecting to InfluxDB: {}", config.influxdb_url);
    info!(
        "Using tags for InfluxDB: product_type={}, serialNumber={}",
        config.product_type, config.serial_number
    );

    // Create InfluxDB client
    let client = Client::new(&config.influxdb_url, &config.influxdb_bucket)
        .with_token(&config.influxdb_token);

    info!("Extracting metrics using pmrep with {} validated metrics...", metrics.len());

    // Build pmrep command
    let mut args = vec![
        "-a".to_string(),
        archive_base.to_str().unwrap().to_string(),
        "-t".to_string(),
        "1sec".to_string(),
        "-o".to_string(),
        "csv".to_string(),
        "-U".to_string(),
        "--ignore-unknown".to_string(),
    ];

    args.extend(metrics.iter().map(|s| s.to_string()));

    info!(
        "Command: pmrep -a {} -t 1sec -o csv -U --ignore-unknown [+ {} metrics]",
        archive_base.display(),
        metrics.len()
    );

    // Start pmrep process
    let mut child = Command::new("pmrep")
        .args(&args)
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .context("Failed to spawn pmrep")?;

    let stdout = child.stdout.take().context("Failed to get stdout")?;
    let reader = BufReader::new(stdout);

    // Save CSV output to file
    let csv_output_file = config.log_dir.join(format!(
        "pmrep_output_{}.csv",
        archive_name.trim_end_matches(".tar.xz")
    ));
    info!("Saving pmrep CSV output to: {:?}", csv_output_file);

    let csv_file = File::create(&csv_output_file)?;
    let mut csv_writer = BufWriter::new(csv_file);

    let mut header: Option<Vec<String>> = None;
    let mut line_count = 0;
    let mut error_count = 0;
    let mut total_points_written = 0;
    let mut batch_count = 0;
    let mut batch_queries = Vec::new();

    info!("Processing pmrep output...");

    for line in reader.lines() {
        let line = line?;
        if line.is_empty() {
            continue;
        }

        // Write to CSV file
        writeln!(csv_writer, "{}", line)?;
        line_count += 1;

        // First line is header
        if header.is_none() {
            // Strip quotes from column names
            let cols: Vec<String> = line
                .split(',')
                .map(|s| s.trim().trim_matches('"').to_string())
                .collect();

            info!("Found {} columns (first column is timestamp)", cols.len());
            header = Some(cols);
            continue;
        }

        let headers = header.as_ref().unwrap();
        let values: Vec<&str> = line.split(',').collect();

        if values.len() != headers.len() {
            continue;
        }

        // Parse timestamp (first column)
        let timestamp_str = values[0].trim();
        let timestamp = match NaiveDateTime::parse_from_str(timestamp_str, "%Y-%m-%d %H:%M:%S") {
            Ok(dt) => DateTime::<Utc>::from_naive_utc_and_offset(dt, Utc),
            Err(_) => {
                error_count += 1;
                continue;
            }
        };

        // Create a query for this timestamp with all fields
        let mut fields = HashMap::new();

        // Add all metrics as fields
        for (i, metric_name) in headers.iter().enumerate().skip(1) {
            let value_str = values[i].trim().trim_matches('"');

            // Skip empty, None, N/A, or ? values
            if value_str.is_empty() || matches!(value_str.to_lowercase().as_str(), "n/a" | "?" | "none" | "null") {
                error_count += 1;
                continue;
            }

            // Parse as float - skip non-numeric values silently
            let value = match value_str.parse::<f64>() {
                Ok(v) => v,
                Err(_) => {
                    error_count += 1;
                    continue;
                }
            };

            // Apply filtering
            if should_skip_value(value_str, &config.pcp_metrics_filter) {
                continue;
            }

            // Sanitize field name
            let field_name = sanitize_field_name(metric_name);

            // Add field (ensure float64 type)
            fields.insert(field_name.clone(), value);

            // Track metric in cache
            if let Err(e) = metrics_cache.add_metric(metric_name) {
                warn!("Failed to add metric to cache: {}", e);
            }
        }

        // Only create query if we have fields
        if !fields.is_empty() {
            let mut query = Timestamp::from(timestamp)
                .into_query(&config.influxdb_measurement)
                .add_tag("product_type", config.product_type.as_str())
                .add_tag("serialNumber", config.serial_number.as_str());

            for (field_name, value) in fields {
                query = query.add_field(&field_name, value);
            }

            batch_queries.push(query);
        }

        // Write batch when it reaches configured size
        if batch_queries.len() >= config.influx_batch_size {
            let batch_size = batch_queries.len();
            client.query(batch_queries).await?;
            total_points_written += batch_size;
            batch_count += 1;

            // Log progress at configured intervals
            if batch_count % config.progress_log_interval == 0 {
                info!("Progress: {} points written ({} batches)...", total_points_written, batch_count);
            }

            batch_queries = Vec::new();
        }
    }

    // Flush CSV writer
    csv_writer.flush()?;
    info!("CSV output saved to: {:?}", csv_output_file);

    // Wait for process to complete
    let status = child.wait()?;
    if !status.success() {
        warn!("pmrep exited with non-zero status: {}", status);
    }

    // Write remaining points
    if !batch_queries.is_empty() {
        let final_batch_size = batch_queries.len();
        info!("Writing final batch of {} points to InfluxDB...", final_batch_size);
        client.query(batch_queries).await?;
        total_points_written += final_batch_size;
    }

    info!("{}", "=".repeat(60));
    info!("EXPORT COMPLETE");
    info!("{}", "=".repeat(60));
    info!("Total data points written: {}", total_points_written);
    info!("Processed {} lines from pmrep", line_count);
    info!("Empty/invalid values skipped: {}", error_count);

    Ok(total_points_written)
}

/// Process a single archive
async fn process_archive(archive_path: &Path, config: &Config, metrics_cache: &mut MetricsCache) -> Result<()> {
    let archive_name = archive_path
        .file_name()
        .and_then(|s| s.to_str())
        .context("Invalid archive filename")?;

    info!("{}", "=".repeat(60));
    info!("Processing archive: {}", archive_name);
    info!("{}", "=".repeat(60));
    info!("START: Processing {}", archive_name);

    let start_time = Instant::now();

    // Extract archive
    let extract_start = Instant::now();
    info!("Extracting archive...");
    let extract_dir = extract_archive(archive_path, &config.extract_dir)?;
    let extract_duration = extract_start.elapsed();

    // Find PCP archive
    let archive_base = find_pcp_archive(&extract_dir)?;
    info!("Found PCP archive: {:?}", archive_base);

    // Metric validation
    let validation_start = Instant::now();
    info!("Starting metric validation...");

    // Load cached validated metrics
    let validated_metrics = match load_validated_metrics_cache(&config.validated_metrics_cache, config.force_revalidate)? {
        Some(metrics) => {
            info!("Using {} cached validated metrics (skipping validation)", metrics.len());
            metrics
        }
        None => {
            info!("No cache found, discovering and validating metrics from archive...");
            let metrics = discover_and_validate_metrics(&archive_base, config)?;

            if metrics.is_empty() {
                return Err(anyhow::anyhow!("No valid metrics found in archive"));
            }

            info!("Discovered and validated {} metrics", metrics.len());

            // Save to cache
            if let Err(e) = save_validated_metrics_cache(&metrics, &config.validated_metrics_cache) {
                warn!("Failed to save validation cache: {}", e);
            }

            metrics
        }
    };

    let validation_duration = validation_start.elapsed();
    info!("Metric validation completed in {:.2} seconds", validation_duration.as_secs_f64());

    // Export to InfluxDB
    let export_start = Instant::now();
    info!("Starting InfluxDB export...");

    export_to_influxdb(&archive_base, archive_name, &validated_metrics, config, metrics_cache).await?;

    let export_duration = export_start.elapsed();
    info!("InfluxDB export completed in {:.2} seconds", export_duration.as_secs_f64());

    // Calculate total processing time
    let total_duration = start_time.elapsed();
    let minutes = total_duration.as_secs() / 60;
    let seconds = total_duration.as_secs_f64() - (minutes as f64 * 60.0);

    info!("Successfully exported {} to InfluxDB", archive_name);
    info!("InfluxDB: {}, Org: {}, Bucket: {}", config.influxdb_url, config.influxdb_org, config.influxdb_bucket);
    info!("TOTAL PROCESSING TIME: {} minutes {:.2} seconds", minutes, seconds);
    info!("   Extraction: {:.2}s", extract_duration.as_secs_f64());
    info!("   Validation: {:.2}s", validation_duration.as_secs_f64());
    info!("   Export: {:.2}s", export_duration.as_secs_f64());

    // Move to processed directory
    let processed_path = config.processed_dir.join(archive_name);
    fs::rename(archive_path, &processed_path)?;
    info!("Moved {} to {:?}", archive_name, config.processed_dir);

    info!("COMPLETE: Finished processing {}", archive_name);

    // Cleanup extraction directory
    if extract_dir.exists() {
        fs::remove_dir_all(&extract_dir)?;
    }

    Ok(())
}

/// Process all archives in watch directory
async fn process_all_archives(config: &Config, metrics_cache: &mut MetricsCache) -> Result<()> {
    info!("{}", "=".repeat(60));
    info!("MANUAL PROCESSING TRIGGERED");
    info!("{}", "=".repeat(60));

    info!("{}", "=".repeat(60));
    info!("DATA TAGGING CONFIGURATION:");
    info!("  PRODUCT_TYPE  = {}", config.product_type);
    info!("  SERIAL_NUMBER = {}", config.serial_number);
    info!("{}", "=".repeat(60));

    // Find archives
    info!("Checking for .tar.xz files in {:?}...", config.watch_dir);

    let mut archives = Vec::new();
    for entry in fs::read_dir(&config.watch_dir)? {
        let entry = entry?;
        let path = entry.path();

        if path.is_file() && path.extension().and_then(|s| s.to_str()) == Some("xz") {
            if let Some(stem) = path.file_stem() {
                if stem.to_str().unwrap_or("").ends_with(".tar") {
                    archives.push(path);
                }
            }
        }
    }

    if archives.is_empty() {
        info!("No files found to process");
        return Ok(());
    }

    info!("Found {} archive(s) to process", archives.len());

    let mut success_count = 0;
    let mut failed_count = 0;

    for archive in archives {
        let archive_name = archive.file_name().and_then(|s| s.to_str()).unwrap_or("unknown");
        info!("Processing: {}", archive_name);

        match process_archive(&archive, config, metrics_cache).await {
            Ok(_) => success_count += 1,
            Err(e) => {
                error!("Failed to process {}: {}", archive_name, e);

                // Move to failed directory
                let failed_path = config.failed_dir.join(archive_name);
                if let Err(move_err) = fs::rename(&archive, &failed_path) {
                    warn!("Failed to move archive to failed: {}", move_err);
                } else {
                    info!("Moved {} to {:?}", archive_name, config.failed_dir);
                }

                failed_count += 1;
            }
        }
    }

    info!("{}", "=".repeat(60));
    info!("PROCESSING COMPLETE: {} successful, {} failed", success_count, failed_count);
    info!("{}", "=".repeat(60));

    Ok(())
}

/// Check InfluxDB connectivity
async fn check_influxdb_connection(url: &str) -> bool {
    match reqwest::get(format!("{}/ping", url)).await {
        Ok(response) => {
            info!("InfluxDB is reachable (HTTP {})", response.status());
            true
        }
        Err(e) => {
            warn!("InfluxDB connectivity issue: {}", e);
            false
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    // Initialize logging
    env_logger::Builder::from_default_env()
        .format_timestamp_secs()
        .init();

    // Load configuration
    let mut config = Config::from_env()?;

    // Create necessary directories
    fs::create_dir_all(&config.watch_dir)?;
    fs::create_dir_all(&config.processed_dir)?;
    fs::create_dir_all(&config.failed_dir)?;
    fs::create_dir_all(&config.log_dir)?;

    // Load tags from .env file
    if let Err(e) = config.load_tags_from_env() {
        warn!("Failed to load tags from .env: {}", e);
    }

    info!("{}", "=".repeat(60));
    info!("PCP Archive to InfluxDB Processor (Rust)");
    info!("{}", "=".repeat(60));
    info!("Watch directory: {:?}", config.watch_dir);
    info!("Extract directory: {:?}", config.extract_dir);
    info!("Processed directory: {:?}", config.processed_dir);
    info!("Failed directory: {:?}", config.failed_dir);
    info!("Log directory: {:?}", config.log_dir);
    info!("InfluxDB URL: {}", config.influxdb_url);
    info!("InfluxDB Measurement: {}", config.influxdb_measurement);
    info!("Static Tags - Product Type: {}, Serial Number: {}", config.product_type, config.serial_number);
    info!("");

    // Initialize metrics cache
    let mut metrics_cache = MetricsCache::new(config.metrics_csv.clone())?;
    info!("Loaded {} existing metrics from cache", metrics_cache.cache.len());

    // Wait for InfluxDB to be ready
    info!("Waiting for InfluxDB to be ready...");
    loop {
        if check_influxdb_connection(&config.influxdb_url).await {
            info!("InfluxDB is ready!");
            break;
        }
        info!("InfluxDB is unavailable - sleeping");
        tokio::time::sleep(Duration::from_secs(5)).await;
    }

    info!("");
    info!("Waiting for manual trigger via web interface...");
    info!("Trigger file: /src/.process_trigger_rust");
    info!("");

    let trigger_file = Path::new("/src/.process_trigger_rust");

    // Main monitoring loop
    loop {
        // Check if trigger file exists
        if trigger_file.exists() {
            info!("TRIGGER DETECTED - Starting processing...");

            // Remove trigger file
            fs::remove_file(trigger_file)?;

            // Process all archives
            if let Err(e) = process_all_archives(&config, &mut metrics_cache).await {
                error!("Error during processing: {}", e);
            }

            info!("Waiting for next trigger...");
        }

        // Sleep for 2 seconds
        tokio::time::sleep(Duration::from_secs(2)).await;
    }
}
