# Auto-Generated PCP Metrics Dashboard

## Overview

A new Grafana dashboard has been automatically generated based on the metrics in `metrics_labels.csv`.

## Dashboard Details

- **File**: `grafana/provisioning/dashboards/json/pcp-auto-dashboard.json`
- **Title**: "PCP Auto-Generated Metrics Dashboard"
- **UID**: `pcp-auto-metrics`
- **Total Metrics**: 9,040 metrics
- **Total Categories**: 83 categories
- **Total Panels**: 1,043 panels

## Organization

The dashboard is organized by metric categories (based on metric name prefixes):

### Major Categories Include:

- **disk.all** (16 metrics) - Overall disk statistics
- **disk.dev** (46 metrics) - Per-device disk metrics
- **disk.dm** (184 metrics) - Device mapper metrics
- **disk.partitions** (64 metrics) - Partition-level metrics
- **filesys.\*** (10 metrics) - Filesystem capacity and usage
- **hinv.\*** (75 metrics) - Hardware inventory
- **kernel.\*** (147 metrics) - Kernel statistics
- **mem.\*** (375 metrics) - Memory statistics
- **network.\*** (1,154 metrics) - Network statistics (interfaces, protocols, etc.)
- **proc.\*** (6,573 metrics) - Process-level metrics
- **psoc.\*** (312 metrics) - PSOC-specific metrics
- **swap.\*** (5 metrics) - Swap space metrics
- **vfs.\*** (7 metrics) - Virtual filesystem statistics
- **xfs.\*** (17 metrics) - XFS filesystem metrics

## Features

### Row Organization
- Each metric category has its own collapsible row
- Row titles show the category name and metric count
- Rows can be collapsed to hide panels and improve navigation

### Panel Layout
- Panels are organized 2 per row (12 columns each)
- Each panel contains up to 10 related metrics for readability
- Large categories are split into multiple panels (e.g., "proc.memory (1-10)", "proc.memory (11-20)", etc.)

### Panel Features
- **Time Series Visualization**: Line charts with 10% fill opacity
- **Legend**: Shows mean, max, and last values
- **Legend Display**: Table format for >5 metrics, list format for ≤5 metrics
- **Multi-tooltip**: Hovering shows values for all series at that timestamp
- **Auto-refresh**: Dashboard refreshes every 30 seconds

### Variables
The dashboard uses the same template variables as the existing dashboard:

- **product_type**: Filter by product type (default: "L5E")
- **serialNumber**: Filter by serial number (default: "341100896")

## Query Pattern

All panels use similar Flux queries:

```flux
from(bucket: "pcp-metrics")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "pcp_metrics")
  |> filter(fn: (r) => r["_field"] == "value")
  |> filter(fn: (r) => r["product_type"] == "${product_type}")
  |> filter(fn: (r) => r["serialNumber"] == "${serialNumber}")
  |> filter(fn: (r) => r["metric"] =~ /^(metric1|metric2|...)$/)
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> pivot(rowKey:["_time"], columnKey: ["metric"], valueColumn: "_value")
```

## Accessing the Dashboard

Once Grafana is running, the dashboard will be available at:

**URL**: http://localhost:3000/d/pcp-auto-metrics/pcp-auto-generated-metrics-dashboard

## Regenerating the Dashboard

To regenerate the dashboard from updated metrics:

```bash
cd /path/to/PCP/src
python generate_dashboard.py
```

This will:
1. Read the latest metrics from `logs/pcp_parser/metrics_labels.csv`
2. Categorize metrics by prefix
3. Generate panels and rows
4. Write the dashboard JSON to `grafana/provisioning/dashboards/json/pcp-auto-dashboard.json`

## Comparison with Existing Dashboard

### Existing Dashboard (`pcp-metrics.json`)
- Manually curated panels
- Focused on specific metrics (CPU freq, temperature, etc.)
- Fixed number of panels
- Custom titles and units

### Auto-Generated Dashboard (`pcp-auto-dashboard.json`)
- Automatically generated from all available metrics
- Organized by metric category
- Dynamically adapts to available metrics
- Comprehensive coverage of all 9,040+ metrics
- Generic time series visualization

## Notes

- The existing dashboard (`pcp-metrics.json`) is **unchanged** and still available
- Both dashboards can coexist and be used simultaneously
- The auto-generated dashboard provides comprehensive metric coverage
- For focused analysis, use the manually curated dashboard
- For exploration and discovery, use the auto-generated dashboard
