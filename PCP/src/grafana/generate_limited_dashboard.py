#!/usr/bin/env python3
"""
Generate Grafana dashboard for Limited View using curated metrics from data_filter
This creates a focused dashboard with ~100 essential metrics organized by category
"""

import json
import os
from pathlib import Path
from collections import defaultdict
import re

# Paths
SCRIPT_DIR = Path(__file__).parent
VALIDATED_METRICS_FILE = SCRIPT_DIR.parent / "input" / "data_filter" / "validated_metrics.txt"
OUTPUT_FILE = SCRIPT_DIR / "provisioning" / "dashboards" / "json" / "pcp-limited-view.json"
EXPORT_JSON_FILE = SCRIPT_DIR.parent.parent / "export.json"
VARIABLES_FILE = SCRIPT_DIR / "variables.txt"

def load_metric_mappings():
    """Load metric to field mappings from variables.txt"""
    mappings = {}

    if not VARIABLES_FILE.exists():
        print(f"WARNING: {VARIABLES_FILE} not found. Will use auto-expansion.")
        return None

    with open(VARIABLES_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('##'):
                continue

            # Parse: "metric -> field1, field2, ..."
            if ' -> ' in line:
                metric, fields_str = line.split(' -> ', 1)
                if fields_str == '(no match)':
                    mappings[metric] = []
                else:
                    fields = [f.strip() for f in fields_str.split(',')]
                    mappings[metric] = fields

    print(f"Loaded {len(mappings)} metric mappings from {VARIABLES_FILE}")
    return mappings

def load_database_fields():
    """Load actual field names from export.json"""
    if not EXPORT_JSON_FILE.exists():
        print(f"WARNING: {EXPORT_JSON_FILE} not found. Will use metric names as-is.")
        return set()

    with open(EXPORT_JSON_FILE, 'r') as f:
        data = json.load(f)
        # Get all field names except metadata
        db_fields = set([k for k in data[0].keys() if k not in ['time', 'product_type', 'serialNumber', 'iid']])

    print(f"Loaded {len(db_fields)} fields from database schema")
    return db_fields

def load_curated_metrics():
    """Load metrics from validated_metrics.txt, skip comments and empty lines"""
    metrics = []
    current_category = None
    category_map = {}

    if not VALIDATED_METRICS_FILE.exists():
        print(f"ERROR: {VALIDATED_METRICS_FILE} not found!")
        return [], {}

    with open(VALIDATED_METRICS_FILE, 'r') as f:
        for line in f:
            line = line.strip()

            # Skip empty lines
            if not line:
                continue

            # Parse category headers (lines starting with ##)
            if line.startswith('##'):
                # Extract category name from comment
                current_category = line.replace('##', '').strip()
                # Remove metric count info like "(10 metrics)"
                if '(' in current_category:
                    current_category = current_category.split('(')[0].strip()
                continue

            # Skip other comments
            if line.startswith('#'):
                continue

            # Add metric with its category
            metrics.append(line)
            if current_category:
                if current_category not in category_map:
                    category_map[current_category] = []
                category_map[current_category].append(line)

    print(f"Loaded {len(metrics)} metrics from {VALIDATED_METRICS_FILE}")
    print(f"Found {len(category_map)} categories")
    return metrics, category_map

def sanitize_field_name(metric):
    """Convert metric name to field name (dots to underscores)"""
    return metric.replace('.', '_').replace('-', '_')

def expand_metric_to_fields(metric, db_fields, mappings=None):
    """
    Expand a metric name to actual database field names.
    Uses mappings from variables.txt if available, otherwise auto-expands.

    Examples:
    - hinv.cpu.clock -> hinv_cpu_clock_cpu0, hinv_cpu_clock_cpu1, ...
    - kernel.all.load -> kernel_all_load_1_minute, kernel_all_load_5_minute, kernel_all_load_15_minute
    - filesys.capacity -> filesys_capacity_/dev/root, filesys_capacity_/dev/sda1, ...

    Always returns at least the sanitized field name (will show no data if not in DB).
    """
    # Use mappings if available
    if mappings is not None and metric in mappings:
        fields = mappings[metric]
        # If empty list (no match), use sanitized name
        if not fields:
            return [sanitize_field_name(metric)]
        return fields

    # Fall back to auto-expansion
    base_field = sanitize_field_name(metric)

    # Check if exact field exists
    if base_field in db_fields:
        return [base_field]

    # Find all fields that start with this base pattern
    matching_fields = [f for f in db_fields if f.startswith(base_field)]

    if matching_fields:
        return sorted(matching_fields)

    # No matches found - return sanitized name anyway
    return [base_field]

def create_panel(panel_id, title, metrics, db_fields, mappings, x, y, w=12, h=8):
    """Create a time series panel for a group of metrics"""
    # Expand metrics to actual database fields
    all_fields = []
    for metric in metrics:
        expanded = expand_metric_to_fields(metric, db_fields, mappings)
        all_fields.extend(expanded)

    # Create SQL SELECT list
    field_list = ', '.join(all_fields)

    # SQL query for InfluxDB 3
    sql_query = f"SELECT time, {field_list} FROM pcp_metrics WHERE product_type = '$product_type' AND \"serialNumber\" = '$serialNumber' AND time >= $__timeFrom AND time <= $__timeTo ORDER BY time"

    return {
        "datasource": {
            "type": "influxdb",
            "uid": "influxdb3-sql"
        },
        "fieldConfig": {
            "defaults": {
                "color": {
                    "mode": "palette-classic"
                },
                "custom": {
                    "drawStyle": "line",
                    "fillOpacity": 10,
                    "lineWidth": 1,
                    "showPoints": "never",
                    "axisPlacement": "auto"
                },
                "mappings": [],
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "green", "value": None}
                    ]
                }
            },
            "overrides": []
        },
        "gridPos": {
            "h": h,
            "w": w,
            "x": x,
            "y": y
        },
        "id": panel_id,
        "options": {
            "legend": {
                "calcs": ["mean", "max", "last"],
                "displayMode": "table",
                "placement": "bottom",
                "showLegend": True
            },
            "tooltip": {
                "mode": "multi",
                "sort": "none"
            }
        },
        "targets": [
            {
                "datasource": {
                    "type": "influxdb",
                    "uid": "influxdb3-sql"
                },
                "rawSql": sql_query,
                "refId": "A",
                "format": "time_series",
                "hide": False
            }
        ],
        "title": title,
        "type": "timeseries"
    }

def create_row_panel(panel_id, title, y):
    """Create a collapsible row panel for grouping"""
    return {
        "collapsed": True,
        "gridPos": {
            "h": 1,
            "w": 24,
            "x": 0,
            "y": y
        },
        "id": panel_id,
        "panels": [],
        "title": title,
        "type": "row"
    }

def generate_dashboard():
    """Generate the Limited View dashboard JSON"""

    # Load database schema and metric mappings
    db_fields = load_database_fields()
    mappings = load_metric_mappings()

    metrics, category_map = load_curated_metrics()

    if not metrics:
        print("No metrics found. Exiting.")
        return

    # Dashboard base structure
    dashboard = {
        "annotations": {
            "list": []
        },
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "id": None,
        "links": [],
        "liveNow": False,
        "panels": [],
        "refresh": "30s",
        "schemaVersion": 38,
        "style": "dark",
        "tags": ["pcp", "limited-view", "curated"],
        "templating": {
            "list": [
                {
                    "current": {
                        "selected": False,
                        "text": "All",
                        "value": "$__all"
                    },
                    "datasource": {
                        "type": "influxdb",
                        "uid": "influxdb3-sql"
                    },
                    "definition": "SELECT DISTINCT product_type FROM pcp_metrics",
                    "hide": 0,
                    "includeAll": True,
                    "multi": False,
                    "name": "product_type",
                    "options": [],
                    "query": "SELECT DISTINCT product_type FROM pcp_metrics",
                    "refresh": 1,
                    "regex": "",
                    "skipUrlSync": False,
                    "sort": 0,
                    "type": "query"
                },
                {
                    "current": {
                        "selected": False,
                        "text": "All",
                        "value": "$__all"
                    },
                    "datasource": {
                        "type": "influxdb",
                        "uid": "influxdb3-sql"
                    },
                    "definition": "SELECT DISTINCT \"serialNumber\" FROM pcp_metrics",
                    "hide": 0,
                    "includeAll": True,
                    "multi": False,
                    "name": "serialNumber",
                    "options": [],
                    "query": "SELECT DISTINCT \"serialNumber\" FROM pcp_metrics",
                    "refresh": 1,
                    "regex": "",
                    "skipUrlSync": False,
                    "sort": 0,
                    "type": "query"
                }
            ]
        },
        "time": {
            "from": "now-6h",
            "to": "now"
        },
        "timepicker": {},
        "timezone": "",
        "title": "PCP Limited View Dashboard - Curated Metrics",
        "uid": "pcp-limited-view",
        "version": 0,
        "weekStart": ""
    }

    panel_id = 1
    y_pos = 0

    # Create panels organized by category
    for category_name, category_metrics in category_map.items():
        # Create a row for this category
        row = create_row_panel(panel_id, f"[{category_name.upper()}] - {len(category_metrics)} metrics", y_pos)
        panel_id += 1
        y_pos += 1

        # Split metrics into panels (max 10 metrics per panel for readability)
        metrics_per_panel = 10
        row_panels = []

        for i in range(0, len(category_metrics), metrics_per_panel):
            chunk = category_metrics[i:i + metrics_per_panel]
            panel_num = (i // metrics_per_panel) + 1
            total_panels = (len(category_metrics) + metrics_per_panel - 1) // metrics_per_panel

            # Determine panel position within row
            panel_x = (len(row_panels) % 2) * 12  # 0 or 12
            panel_y = (len(row_panels) // 2) * 8 + 1  # Stack vertically every 2 panels

            panel = create_panel(
                panel_id=panel_id,
                title=f"[{category_name}] Metrics {i+1}-{min(i+metrics_per_panel, len(category_metrics))} of {len(category_metrics)}",
                metrics=chunk,
                db_fields=db_fields,
                mappings=mappings,
                x=panel_x,
                y=panel_y,
                w=12,
                h=8
            )
            row_panels.append(panel)
            panel_id += 1

        # Add panels to row
        row["panels"] = row_panels
        dashboard["panels"].append(row)

    # Write dashboard to file
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(dashboard, f, indent=2)

    print(f"\n[SUCCESS] Dashboard generated successfully!")
    print(f"[OUTPUT] File: {OUTPUT_FILE}")
    print(f"[METRICS] Total: {len(metrics)}")
    print(f"[CATEGORIES] Total: {len(category_map)}")
    print(f"[PANELS] Total: {panel_id - 1}")
    print(f"\n[URL] Dashboard will be available at:")
    print(f"      http://localhost:3000/d/pcp-limited-view/pcp-limited-view-dashboard-curated-metrics")
    print(f"\n[INFO] Grafana will auto-reload the dashboard within 30 seconds")

if __name__ == "__main__":
    print("=" * 60)
    print("Generating Limited View Dashboard from Curated Metrics")
    print("=" * 60)
    generate_dashboard()
