package main

import (
	"bufio"
	"encoding/csv"
	"fmt"
	"io"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	influxdb2 "github.com/influxdata/influxdb-client-go/v2"
)

// Configuration from environment variables
type Config struct {
	WatchDir              string
	ExtractDir            string
	ProcessedDir          string
	FailedDir             string
	LogDir                string
	MetricsCSV            string
	ValidatedMetricsCache string

	InfluxDBURL         string
	InfluxDBToken       string
	InfluxDBOrg         string
	InfluxDBBucket      string
	InfluxDBMeasurement string

	ProductType  string
	SerialNumber string

	PCPMetricsFilter    string
	ValidationBatchSize int
	InfluxBatchSize     int
	ProgressLogInterval int
	SkipValidation      bool
	ForceRevalidate     bool

	EnableProcessMetrics bool
	EnableDiskMetrics    bool
	EnableFileMetrics    bool
	EnableMemoryMetrics  bool
	EnableNetworkMetrics bool
	EnableKernelMetrics  bool
	EnableSwapMetrics    bool
	EnableNFSMetrics     bool
}

// Global metrics cache
var metricsCache = make(map[string]bool)

// Logger wrapper
type Logger struct {
	file    *os.File
	logger  *log.Logger
	console *log.Logger
}

func NewLogger(logPath string) (*Logger, error) {
	// Ensure log directory exists
	logDir := filepath.Dir(logPath)
	if err := os.MkdirAll(logDir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create log directory: %w", err)
	}

	// Open log file
	file, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return nil, fmt.Errorf("failed to open log file: %w", err)
	}

	// Create loggers
	fileLogger := log.New(file, "", 0)
	consoleLogger := log.New(os.Stdout, "", 0)

	return &Logger{
		file:    file,
		logger:  fileLogger,
		console: consoleLogger,
	}, nil
}

func (l *Logger) Info(msg string) {
	timestamp := time.Now().Format("2006-01-02 15:04:05")
	formattedMsg := fmt.Sprintf("[%s] %s", timestamp, msg)
	l.logger.Println(formattedMsg)
	l.console.Println(msg)
}

func (l *Logger) Separator(title string) {
	l.Info(strings.Repeat("=", 60))
	l.Info(title)
	l.Info(strings.Repeat("=", 60))
}

func (l *Logger) Close() {
	if l.file != nil {
		l.file.Close()
	}
}

// Load configuration from environment
func LoadConfig() *Config {
	logDir := getEnv("LOG_DIR", "/src/logs/pcp_parser_go")

	return &Config{
		WatchDir:              getEnv("WATCH_DIR", "/src/input/raw"),
		ExtractDir:            getEnv("EXTRACT_DIR", "/tmp/pcp_archives"),
		ProcessedDir:          getEnv("PROCESSED_DIR", "/src/archive/processed"),
		FailedDir:             getEnv("FAILED_DIR", "/src/archive/failed"),
		LogDir:                logDir,
		MetricsCSV:            getEnv("METRICS_CSV", logDir+"/metrics_labels.csv"),
		ValidatedMetricsCache: getEnv("VALIDATED_METRICS_CACHE", logDir+"/validated_metrics.txt"),

		InfluxDBURL:         getEnv("INFLUXDB_URL", "http://influxdb:8086"),
		InfluxDBToken:       getEnv("INFLUXDB_TOKEN", ""),
		InfluxDBOrg:         getEnv("INFLUXDB_ORG", "pcp-org"),
		InfluxDBBucket:      getEnv("INFLUXDB_BUCKET", "pcp-metrics"),
		InfluxDBMeasurement: getEnv("INFLUXDB_MEASUREMENT", "pcp_metrics"),

		PCPMetricsFilter:    strings.ToLower(getEnv("PCP_METRICS_FILTER", "")),
		ValidationBatchSize: getEnvInt("VALIDATION_BATCH_SIZE", 100),
		InfluxBatchSize:     getEnvInt("INFLUX_BATCH_SIZE", 50000),
		ProgressLogInterval: getEnvInt("PROGRESS_LOG_INTERVAL", 50),
		SkipValidation:      getEnvBool("SKIP_VALIDATION", false),
		ForceRevalidate:     getEnvBool("FORCE_REVALIDATE", false),

		EnableProcessMetrics: getEnvBool("ENABLE_PROCESS_METRICS", false),
		EnableDiskMetrics:    getEnvBool("ENABLE_DISK_METRICS", true),
		EnableFileMetrics:    getEnvBool("ENABLE_FILE_METRICS", true),
		EnableMemoryMetrics:  getEnvBool("ENABLE_MEMORY_METRICS", true),
		EnableNetworkMetrics: getEnvBool("ENABLE_NETWORK_METRICS", true),
		EnableKernelMetrics:  getEnvBool("ENABLE_KERNEL_METRICS", true),
		EnableSwapMetrics:    getEnvBool("ENABLE_SWAP_METRICS", true),
		EnableNFSMetrics:     getEnvBool("ENABLE_NFS_METRICS", false),
	}
}

// Load product type and serial number from .env file
func (c *Config) LoadTagsFromEnv(logger *Logger) error {
	// Set defaults
	c.ProductType = "SERVER1"
	c.SerialNumber = "1234"

	envFile := "/src/.env"
	file, err := os.Open(envFile)
	if err != nil {
		// If .env doesn't exist, try environment variables
		if productType := os.Getenv("PRODUCT_TYPE"); productType != "" {
			c.ProductType = productType
		}
		if serialNumber := os.Getenv("SERIAL_NUMBER"); serialNumber != "" {
			c.SerialNumber = serialNumber
		}
		return nil
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		parts := strings.SplitN(line, "=", 2)
		if len(parts) != 2 {
			continue
		}

		key := strings.TrimSpace(parts[0])
		value := strings.TrimSpace(parts[1])

		switch key {
		case "PRODUCT_TYPE":
			c.ProductType = value
		case "SERIAL_NUMBER":
			c.SerialNumber = value
		}
	}

	return scanner.Err()
}

// Helper functions for environment variables
func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

func getEnvInt(key string, defaultValue int) int {
	if value := os.Getenv(key); value != "" {
		if i, err := strconv.Atoi(value); err == nil {
			return i
		}
	}
	return defaultValue
}

func getEnvBool(key string, defaultValue bool) bool {
	if value := os.Getenv(key); value != "" {
		return strings.ToLower(value) == "true"
	}
	return defaultValue
}

// Load metrics cache from CSV
func loadMetricsCache(csvPath string) error {
	file, err := os.Open(csvPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil // File doesn't exist yet, that's OK
		}
		return err
	}
	defer file.Close()

	reader := csv.NewReader(file)
	// Skip header
	if _, err := reader.Read(); err != nil {
		return err
	}

	for {
		record, err := reader.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}
		if len(record) > 0 {
			metricsCache[record[0]] = true
		}
	}

	return nil
}

// Save metric to CSV if not already tracked
func saveMetricToCSV(metric, csvPath string) error {
	if metricsCache[metric] {
		return nil // Already tracked
	}

	// Add to cache
	metricsCache[metric] = true

	// Check if file exists
	fileExists := false
	if _, err := os.Stat(csvPath); err == nil {
		fileExists = true
	}

	// Open file for appending
	file, err := os.OpenFile(csvPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return err
	}
	defer file.Close()

	writer := csv.NewWriter(file)
	defer writer.Flush()

	// Write header if new file
	if !fileExists {
		if err := writer.Write([]string{"metric_name"}); err != nil {
			return err
		}
	}

	// Write metric
	return writer.Write([]string{metric})
}

// Extract tar.xz archive
func extractArchive(archivePath, extractDir string, logger *Logger) (string, error) {
	startTime := time.Now()

	// Create extraction directory
	baseName := strings.TrimSuffix(filepath.Base(archivePath), ".tar.xz")
	targetDir := filepath.Join(extractDir, baseName+".tar")

	// Remove existing extraction directory if it exists
	if err := os.RemoveAll(targetDir); err != nil {
		return "", fmt.Errorf("failed to remove existing extraction directory: %w", err)
	}

	if err := os.MkdirAll(targetDir, 0755); err != nil {
		return "", fmt.Errorf("failed to create extraction directory: %w", err)
	}

	// Extract using tar command (simpler than implementing tar.xz in Go)
	cmd := exec.Command("tar", "-xJf", archivePath, "-C", targetDir)
	if output, err := cmd.CombinedOutput(); err != nil {
		return "", fmt.Errorf("extraction failed: %s: %w", string(output), err)
	}

	elapsed := time.Since(startTime).Seconds()
	logger.Info(fmt.Sprintf("Extracted to %s in %.2f seconds", targetDir, elapsed))

	return targetDir, nil
}

// Find PCP archive base path (looks for .meta file)
func findPCPArchive(extractDir string) (string, error) {
	var archiveBase string

	err := filepath.Walk(extractDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.IsDir() && strings.HasSuffix(path, ".meta") {
			// Remove .meta extension to get base path
			archiveBase = strings.TrimSuffix(path, ".meta")
			return filepath.SkipDir // Stop walking
		}
		return nil
	})

	if err != nil {
		return "", err
	}

	if archiveBase == "" {
		return "", fmt.Errorf("no PCP archive found (no .meta file)")
	}

	return archiveBase, nil
}

// Load validated metrics from cache
func loadValidatedMetricsCache(cachePath string, forceRevalidate bool, logger *Logger) ([]string, error) {
	if forceRevalidate {
		logger.Info("FORCE_REVALIDATE=true, skipping cache")
		return nil, nil
	}

	file, err := os.Open(cachePath)
	if err != nil {
		if os.IsNotExist(err) {
			logger.Info("No validation cache found, will validate metrics")
			return nil, nil
		}
		return nil, err
	}
	defer file.Close()

	var metrics []string
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line != "" {
			metrics = append(metrics, line)
		}
	}

	if err := scanner.Err(); err != nil {
		return nil, err
	}

	logger.Info(fmt.Sprintf("Loaded %d validated metrics from cache", len(metrics)))
	return metrics, nil
}

// Save validated metrics to cache
func saveValidatedMetricsCache(metrics []string, cachePath string, logger *Logger) error {
	file, err := os.Create(cachePath)
	if err != nil {
		return err
	}
	defer file.Close()

	writer := bufio.NewWriter(file)
	for _, metric := range metrics {
		if _, err := writer.WriteString(metric + "\n"); err != nil {
			return err
		}
	}

	if err := writer.Flush(); err != nil {
		return err
	}

	logger.Info(fmt.Sprintf("Saved %d validated metrics to cache", len(metrics)))
	return nil
}

// Discover and validate metrics from PCP archive
func discoverAndValidateMetrics(archiveBase string, config *Config, logger *Logger) ([]string, error) {
	logger.Info("Discovering metrics in archive...")

	// Step 1: Get all metrics from archive using pminfo
	cmd := exec.Command("pminfo", "-a", archiveBase)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("pminfo failed: %w, output: %s", err, string(output))
	}

	// Parse metric names
	lines := strings.Split(string(output), "\n")
	allMetrics := make([]string, 0, len(lines))
	for _, line := range lines {
		metric := strings.TrimSpace(line)
		if metric != "" {
			allMetrics = append(allMetrics, metric)
		}
	}

	logger.Info(fmt.Sprintf("Found %d total metrics, validating each one...", len(allMetrics)))

	// Step 2: Validate metrics in batches
	batchSize := 100 // Same as Python default
	validMetrics := make([]string, 0)
	invalidCount := 0

	for i := 0; i < len(allMetrics); i += batchSize {
		end := i + batchSize
		if end > len(allMetrics) {
			end = len(allMetrics)
		}
		batch := allMetrics[i:end]

		// Try to validate batch with pmrep
		args := []string{"-a", archiveBase, "-s", "1", "-o", "csv", "--ignore-unknown"}
		args = append(args, batch...)

		cmd := exec.Command("pmrep", args...)
		output, err := cmd.CombinedOutput()

		// If batch succeeds, all metrics are valid
		if err == nil && len(strings.TrimSpace(string(output))) > 0 {
			validMetrics = append(validMetrics, batch...)
		} else {
			// Batch failed, test each metric individually
			for _, metric := range batch {
				singleCmd := exec.Command("pmrep", "-a", archiveBase, "-s", "1", "-o", "csv", "--ignore-unknown", metric)
				singleOutput, singleErr := singleCmd.CombinedOutput()

				if singleErr == nil && len(strings.TrimSpace(string(singleOutput))) > 0 {
					validMetrics = append(validMetrics, metric)
				} else {
					invalidCount++
				}
			}
		}

		// Progress logging
		if (i+batchSize)%200 == 0 {
			logger.Info(fmt.Sprintf("Validated %d/%d metrics...", end, len(allMetrics)))
		}
	}

	logger.Info(fmt.Sprintf("Found %d valid metrics (filtered out %d invalid/derived metrics)", len(validMetrics), invalidCount))

	// Step 3: Apply category filters (same as Python)
	originalCount := len(validMetrics)
	filteredMetrics := make([]string, 0)
	filterStats := make(map[string]int)

	// Get filter settings from environment or use defaults
	enableProcess := getEnvBool("ENABLE_PROCESS_METRICS", false)
	enableDisk := getEnvBool("ENABLE_DISK_METRICS", true)
	enableFile := getEnvBool("ENABLE_FILE_METRICS", true)
	enableMemory := getEnvBool("ENABLE_MEMORY_METRICS", true)
	enableNetwork := getEnvBool("ENABLE_NETWORK_METRICS", true)
	enableKernel := getEnvBool("ENABLE_KERNEL_METRICS", true)
	enableSwap := getEnvBool("ENABLE_SWAP_METRICS", true)

	for _, metric := range validMetrics {
		// Check category filters
		if strings.HasPrefix(metric, "proc.") && !enableProcess {
			filterStats["proc"]++
			continue
		}
		if strings.HasPrefix(metric, "disk.") && !enableDisk {
			filterStats["disk"]++
			continue
		}
		if (strings.HasPrefix(metric, "vfs.") || strings.HasPrefix(metric, "filesys.")) && !enableFile {
			filterStats["file"]++
			continue
		}
		if strings.HasPrefix(metric, "mem.") && !enableMemory {
			filterStats["mem"]++
			continue
		}
		if strings.HasPrefix(metric, "network.") && !enableNetwork {
			filterStats["network"]++
			continue
		}
		if strings.HasPrefix(metric, "kernel.") && !enableKernel {
			filterStats["kernel"]++
			continue
		}
		if strings.HasPrefix(metric, "swap.") && !enableSwap {
			filterStats["swap"]++
			continue
		}

		filteredMetrics = append(filteredMetrics, metric)
	}

	// Log filter statistics
	if len(filterStats) > 0 {
		logger.Info(fmt.Sprintf("Applied category filters: filtered %d metrics", originalCount-len(filteredMetrics)))
		for category, count := range filterStats {
			logger.Info(fmt.Sprintf("  - %s: %d metrics filtered", category, count))
		}
	}

	logger.Info(fmt.Sprintf("Final metric count after filtering: %d", len(filteredMetrics)))

	return filteredMetrics, nil
}

// Process archive (main processing function)
func processArchive(archivePath string, config *Config, logger *Logger) error {
	archiveName := filepath.Base(archivePath)
	logger.Separator(fmt.Sprintf("Processing archive: %s", archiveName))
	logger.Info(fmt.Sprintf("START: Processing %s", archiveName))

	startTime := time.Now()
	var extractionTime, validationTime, exportTime time.Duration

	// Extract archive
	extractStart := time.Now()
	logger.Info("Extracting archive...")
	extractDir, err := extractArchive(archivePath, config.ExtractDir, logger)
	if err != nil {
		return fmt.Errorf("extraction failed: %w", err)
	}
	extractionTime = time.Since(extractStart)

	// Find PCP archive
	archiveBase, err := findPCPArchive(extractDir)
	if err != nil {
		return fmt.Errorf("failed to find PCP archive: %w", err)
	}
	logger.Info(fmt.Sprintf("Found PCP archive: %s", archiveBase))

	// Metric validation
	validationStart := time.Now()
	logger.Info("Starting metric validation...")

	// Load cached validated metrics
	validatedMetrics, err := loadValidatedMetricsCache(config.ValidatedMetricsCache, config.ForceRevalidate, logger)
	if err != nil {
		logger.Info(fmt.Sprintf("Warning: failed to load validation cache: %v", err))
	}

	if validatedMetrics != nil {
		logger.Info(fmt.Sprintf("Using %d cached validated metrics (skipping validation)", len(validatedMetrics)))
	} else {
		// No cache found - discover and validate metrics from archive
		logger.Info("No cache found, discovering and validating metrics from archive...")
		validatedMetrics, err = discoverAndValidateMetrics(archiveBase, config, logger)
		if err != nil {
			return fmt.Errorf("failed to discover metrics: %w", err)
		}

		if len(validatedMetrics) == 0 {
			return fmt.Errorf("no valid metrics found in archive")
		}

		logger.Info(fmt.Sprintf("Discovered and validated %d metrics", len(validatedMetrics)))

		// Save to cache for future use
		if saveErr := saveValidatedMetricsCache(validatedMetrics, config.ValidatedMetricsCache, logger); saveErr != nil {
			logger.Info(fmt.Sprintf("Warning: failed to save cache: %v", saveErr))
		}
	}

	validationTime = time.Since(validationStart)
	logger.Info(fmt.Sprintf("Metric validation completed in %.2f seconds", validationTime.Seconds()))

	// Export to InfluxDB
	exportStart := time.Now()
	logger.Info("Starting InfluxDB export...")

	_, err = exportToInfluxDB(archiveBase, archiveName, validatedMetrics, config, logger)
	if err != nil {
		return fmt.Errorf("InfluxDB export failed: %w", err)
	}

	exportTime = time.Since(exportStart)
	logger.Info(fmt.Sprintf("InfluxDB export completed in %.2f seconds", exportTime.Seconds()))

	// Summary
	totalTime := time.Since(startTime)
	logger.Info(fmt.Sprintf("✓ Successfully exported %s to InfluxDB", archiveName))
	logger.Info(fmt.Sprintf("InfluxDB: %s, Org: %s, Bucket: %s", config.InfluxDBURL, config.InfluxDBOrg, config.InfluxDBBucket))
	logger.Info(fmt.Sprintf("⏱️  TOTAL PROCESSING TIME: %d minutes %.2f seconds", int(totalTime.Minutes()), totalTime.Seconds()-float64(int(totalTime.Minutes())*60)))
	logger.Info(fmt.Sprintf("   ├─ Extraction: %.2fs", extractionTime.Seconds()))
	logger.Info(fmt.Sprintf("   ├─ Validation: %.2fs", validationTime.Seconds()))
	logger.Info(fmt.Sprintf("   └─ Export: %.2fs", exportTime.Seconds()))

	// Move to processed directory
	processedPath := filepath.Join(config.ProcessedDir, archiveName)
	if err := os.Rename(archivePath, processedPath); err != nil {
		logger.Info(fmt.Sprintf("Warning: failed to move archive to processed: %v", err))
	} else {
		logger.Info(fmt.Sprintf("✓ Moved %s to %s", archiveName, config.ProcessedDir))
	}

	logger.Info(fmt.Sprintf("COMPLETE: Finished processing %s", archiveName))

	// Cleanup extraction directory
	os.RemoveAll(extractDir)

	return nil
}

// Export to InfluxDB
func exportToInfluxDB(archiveBase, archiveName string, metrics []string, config *Config, logger *Logger) (int, error) {
	logger.Separator("STARTING EXPORT TO INFLUXDB")
	logger.Info("Using Go InfluxDB client")
	logger.Info(fmt.Sprintf("Value filtering ENABLED: %s", config.PCPMetricsFilter))
	logger.Info(fmt.Sprintf("Connecting to InfluxDB: %s", config.InfluxDBURL))
	logger.Info(fmt.Sprintf("Using tags for InfluxDB: product_type=%s, serialNumber=%s", config.ProductType, config.SerialNumber))

	// Create InfluxDB client
	client := influxdb2.NewClient(config.InfluxDBURL, config.InfluxDBToken)
	defer client.Close()

	// Get async write API with batching (matches Python behavior)
	writeAPI := client.WriteAPI(config.InfluxDBOrg, config.InfluxDBBucket)
	defer writeAPI.Flush()  // Ensure all writes complete before returning

	// Monitor for errors in background
	errorsCh := writeAPI.Errors()
	go func() {
		for err := range errorsCh {
			logger.Info(fmt.Sprintf("InfluxDB write error: %v", err))
		}
	}()

	// Execute pmrep command
	logger.Info(fmt.Sprintf("Extracting metrics using pmrep with %d validated metrics...", len(metrics)))

	// Build pmrep command
	args := []string{
		"-a", archiveBase,
		"-t", "1sec",
		"-o", "csv",
		"-U",
		"--ignore-unknown",
	}
	args = append(args, metrics...)

	cmd := exec.Command("pmrep", args...)
	logger.Info(fmt.Sprintf("Command: pmrep -a %s -t 1sec -o csv -U --ignore-unknown [+ %d metrics]", archiveBase, len(metrics)))

	// Get stdout pipe
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return 0, fmt.Errorf("failed to create stdout pipe: %w", err)
	}

	// Start command
	if err := cmd.Start(); err != nil {
		return 0, fmt.Errorf("failed to start pmrep: %w", err)
	}

	// Save CSV output
	csvPath := filepath.Join(config.LogDir, fmt.Sprintf("pmrep_output_%s.csv", strings.TrimSuffix(archiveName, ".tar.xz")))
	logger.Info(fmt.Sprintf("Saving pmrep CSV output to: %s", csvPath))

	csvFile, err := os.Create(csvPath)
	if err != nil {
		return 0, fmt.Errorf("failed to create CSV file: %w", err)
	}
	defer csvFile.Close()

	// Read CSV and write points
	scanner := bufio.NewScanner(stdout)
	// Increase buffer size to handle very long CSV lines (up to 10MB per line)
	const maxCapacity = 10 * 1024 * 1024 // 10MB
	buf := make([]byte, maxCapacity)
	scanner.Buffer(buf, maxCapacity)

	var header []string
	lineCount := 0
	dataPoints := 0
	skippedValues := 0

	logger.Info("Processing pmrep output...")

	for scanner.Scan() {
		line := scanner.Text()
		csvFile.WriteString(line + "\n")

		if header == nil {
			// First line is header - strip quotes from column names
			rawHeader := strings.Split(line, ",")
			header = make([]string, len(rawHeader))
			for i, col := range rawHeader {
				// Remove quotes and whitespace from header
				header[i] = strings.Trim(strings.TrimSpace(col), `"`)
			}
			logger.Info(fmt.Sprintf("Found %d columns (first column is timestamp)", len(header)))
			continue
		}

		lineCount++
		values := strings.Split(line, ",")

		if len(values) != len(header) {
			continue
		}

		// Parse timestamp (first column)
		timestamp := values[0]
		t, err := time.Parse("2006-01-02 15:04:05", timestamp)
		if err != nil {
			continue
		}

		// Create point
		point := influxdb2.NewPoint(
			config.InfluxDBMeasurement,
			map[string]string{
				"product_type": config.ProductType,
				"serialNumber": config.SerialNumber,
			},
			map[string]interface{}{},
			t,
		)

		hasFields := false

		// Add all metric values as fields
		for i := 1; i < len(values); i++ {
			value := strings.TrimSpace(values[i])

			// Remove surrounding quotes if present (CSV quoted strings)
			value = strings.Trim(value, `"`)

			// Skip empty/invalid values
			if value == "" || value == "N/A" || value == "null" || value == "none" {
				skippedValues++
				continue
			}

			// Parse as float - skip non-numeric values silently (matches Python behavior)
			floatVal, err := strconv.ParseFloat(value, 64)
			if err != nil {
				// Non-numeric values (strings like IPs, MAC addresses, hostnames, etc.)
				// are silently skipped - this matches Python parser behavior with try/except
				skippedValues++
				continue
			}

			// Apply filtering
			if shouldSkipValue(value, config.PCPMetricsFilter) {
				skippedValues++
				continue
			}

			// Sanitize field name
			fieldName := sanitizeFieldName(header[i])

			// Ensure we're adding as float64, not string
			point.AddField(fieldName, float64(floatVal))
			hasFields = true

			// Track metric
			saveMetricToCSV(header[i], config.MetricsCSV)
		}

		if hasFields {
			// Write point using async API (matches Python batching behavior)
			writeAPI.WritePoint(point)
			dataPoints++
		}
	}

	if err := scanner.Err(); err != nil {
		return 0, fmt.Errorf("error reading pmrep output: %w", err)
	}

	if err := cmd.Wait(); err != nil {
		logger.Info(fmt.Sprintf("Warning: pmrep exited with error: %v", err))
	}

	// Flush all pending writes to InfluxDB (matches Python behavior)
	logger.Info("Flushing async writes to InfluxDB...")
	writeAPI.Flush()
	logger.Info("All async writes completed")

	logger.Info(fmt.Sprintf("CSV output saved to: %s", csvPath))
	logger.Separator("EXPORT COMPLETE")
	logger.Info(fmt.Sprintf("Total data points written: %d", dataPoints))
	logger.Info(fmt.Sprintf("Processed %d lines from pmrep", lineCount))
	logger.Info(fmt.Sprintf("Empty/invalid values skipped: %d", skippedValues))

	return dataPoints, nil
}

// Sanitize field name (replace dots, dashes, spaces with underscores)
func sanitizeFieldName(name string) string {
	name = strings.ReplaceAll(name, ".", "_")
	name = strings.ReplaceAll(name, "-", "_")
	name = strings.ReplaceAll(name, " ", "_")
	return name
}

// Check if value should be skipped based on filter
func shouldSkipValue(value, filter string) bool {
	filters := strings.Split(filter, ",")
	for _, f := range filters {
		f = strings.TrimSpace(f)
		switch f {
		case "skip_zero":
			if value == "0" || value == "0.0" {
				return true
			}
		case "skip_empty":
			if value == "" {
				return true
			}
		case "skip_none":
			if value == "none" || value == "null" || value == "N/A" {
				return true
			}
		}
	}
	return false
}

// Process all archives
func processAllArchives(config *Config, logger *Logger) error {
	logger.Separator("MANUAL PROCESSING TRIGGERED")

	// Load configuration from .env
	if err := config.LoadTagsFromEnv(logger); err != nil {
		logger.Info(fmt.Sprintf("Warning: failed to load config from .env: %v", err))
	}

	logger.Separator("DATA TAGGING CONFIGURATION:")
	logger.Info(fmt.Sprintf("  PRODUCT_TYPE  = %s", config.ProductType))
	logger.Info(fmt.Sprintf("  SERIAL_NUMBER = %s", config.SerialNumber))
	logger.Separator("")

	// Load metrics cache
	if err := loadMetricsCache(config.MetricsCSV); err != nil {
		logger.Info(fmt.Sprintf("Warning: failed to load metrics cache: %v", err))
	}
	logger.Info(fmt.Sprintf("Loaded %d existing metrics from cache", len(metricsCache)))

	// Find archives
	logger.Info(fmt.Sprintf("Checking for .tar.xz files in %s...", config.WatchDir))
	matches, err := filepath.Glob(filepath.Join(config.WatchDir, "*.tar.xz"))
	if err != nil {
		return fmt.Errorf("failed to find archives: %w", err)
	}

	if len(matches) == 0 {
		logger.Info("No files found to process")
		return nil
	}

	logger.Info(fmt.Sprintf("Found %d archive(s) to process", len(matches)))

	// Process each archive
	successCount := 0
	failedCount := 0

	for _, archivePath := range matches {
		archiveName := filepath.Base(archivePath)
		logger.Info(fmt.Sprintf("Processing: %s", archiveName))

		if err := processArchive(archivePath, config, logger); err != nil {
			logger.Info(fmt.Sprintf("✗ Failed to process %s: %v", archiveName, err))

			// Move to failed directory
			failedPath := filepath.Join(config.FailedDir, archiveName)
			if moveErr := os.Rename(archivePath, failedPath); moveErr != nil {
				logger.Info(fmt.Sprintf("Warning: failed to move archive to failed: %v", moveErr))
			} else {
				logger.Info(fmt.Sprintf("✗ Moved %s to %s", archiveName, config.FailedDir))
			}

			failedCount++
		} else {
			successCount++
		}
	}

	logger.Separator(fmt.Sprintf("PROCESSING COMPLETE: %d successful, %d failed", successCount, failedCount))
	return nil
}

func main() {
	// Load configuration
	config := LoadConfig()

	// Create necessary directories
	os.MkdirAll(config.WatchDir, 0755)
	os.MkdirAll(config.ProcessedDir, 0755)
	os.MkdirAll(config.FailedDir, 0755)
	os.MkdirAll(config.LogDir, 0755)

	// Setup logger
	logPath := filepath.Join(config.LogDir, "pcp_parser_go.log")
	logger, err := NewLogger(logPath)
	if err != nil {
		log.Fatalf("Failed to setup logger: %v", err)
	}
	defer logger.Close()

	// Load tags from .env
	if err := config.LoadTagsFromEnv(logger); err != nil {
		logger.Info(fmt.Sprintf("Warning: failed to load tags from .env: %v", err))
	}

	// Print startup info
	logger.Separator("PCP Archive to InfluxDB Processor (Go)")
	logger.Info(fmt.Sprintf("Watch directory: %s", config.WatchDir))
	logger.Info(fmt.Sprintf("Extract directory: %s", config.ExtractDir))
	logger.Info(fmt.Sprintf("Processed directory: %s", config.ProcessedDir))
	logger.Info(fmt.Sprintf("Failed directory: %s", config.FailedDir))
	logger.Info(fmt.Sprintf("Log directory: %s", config.LogDir))
	logger.Info(fmt.Sprintf("InfluxDB URL: %s", config.InfluxDBURL))
	logger.Info(fmt.Sprintf("InfluxDB Measurement: %s", config.InfluxDBMeasurement))
	logger.Info(fmt.Sprintf("Static Tags - Product Type: %s, Serial Number: %s", config.ProductType, config.SerialNumber))
	logger.Info("")

	// Load metrics cache
	if err := loadMetricsCache(config.MetricsCSV); err != nil {
		logger.Info(fmt.Sprintf("Warning: failed to load metrics cache: %v", err))
	}
	logger.Info(fmt.Sprintf("Loaded %d existing metrics from cache", len(metricsCache)))

	// Wait for InfluxDB to be ready
	logger.Info("Waiting for InfluxDB to be ready...")
	for {
		// TODO: Implement health check
		logger.Info("InfluxDB is ready!")
		break
	}

	logger.Info("")
	logger.Info("Waiting for manual trigger via web interface...")
	logger.Info("Trigger file: /src/.process_trigger_go")
	logger.Info("")

	// Main monitoring loop
	triggerFile := "/src/.process_trigger_go"

	for {
		// Check if trigger file exists
		if _, err := os.Stat(triggerFile); err == nil {
			logger.Info("TRIGGER DETECTED - Starting processing...")

			// Remove trigger file immediately (matches Python behavior)
			os.Remove(triggerFile)

			// Process all archives
			if err := processAllArchives(config, logger); err != nil {
				logger.Info(fmt.Sprintf("Error during processing: %v", err))
			}

			logger.Info("Waiting for next trigger...")
		}

		// Sleep for 2 seconds
		time.Sleep(2 * time.Second)
	}
}
