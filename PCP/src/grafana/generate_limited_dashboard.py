#!/usr/bin/env python3
"""
Generate Grafana dashboard for Limited View using curated metrics from data_filter
This creates a focused dashboard with ~100 essential metrics organized by category
"""

import json
import os
from pathlib import Path
from collections import defaultdict

# Paths
SCRIPT_DIR = Path(__file__).parent
VALIDATED_METRICS_FILE = SCRIPT_DIR.parent / "input" / "data_filter" / "validated_metrics.txt"
OUTPUT_FILE = SCRIPT_DIR / "provisioning" / "dashboards" / "json" / "pcp-limited-view.json"

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

def create_panel(panel_id, title, metrics, x, y, w=12, h=8):
    """Create a time series panel for a group of metrics"""
    # Convert metric names to field names
    field_names = [sanitize_field_name(m) for m in metrics]
    field_regex = '|'.join(field_names)

    return {
        "datasource": {
            "type": "influxdb",
            "uid": "influxdb"
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
                    "uid": "influxdb"
                },
                "query": f'''from(bucket: "pcp-metrics")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "pcp_metrics")
  |> filter(fn: (r) => r["product_type"] =~ /${{product_type}}/)
  |> filter(fn: (r) => r["serialNumber"] =~ /${{serialNumber}}/)
  |> filter(fn: (r) => r["_field"] =~ /^({field_regex})$/)
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)''',
                "refId": "A"
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
                        "uid": "influxdb"
                    },
                    "definition": "import \"influxdata/influxdb/v1\"\nv1.tagValues(bucket: \"pcp-metrics\", tag: \"product_type\", start: -30d)",
                    "hide": 0,
                    "includeAll": True,
                    "multi": False,
                    "name": "product_type",
                    "options": [],
                    "query": "import \"influxdata/influxdb/v1\"\nv1.tagValues(bucket: \"pcp-metrics\", tag: \"product_type\", start: -30d)",
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
                        "uid": "influxdb"
                    },
                    "definition": "import \"influxdata/influxdb/v1\"\nv1.tagValues(bucket: \"pcp-metrics\", tag: \"serialNumber\", start: -30d)",
                    "hide": 0,
                    "includeAll": True,
                    "multi": False,
                    "name": "serialNumber",
                    "options": [],
                    "query": "import \"influxdata/influxdb/v1\"\nv1.tagValues(bucket: \"pcp-metrics\", tag: \"serialNumber\", start: -30d)",
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
