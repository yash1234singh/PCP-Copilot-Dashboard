#!/usr/bin/env python3
"""
Generate Grafana Dashboard from metrics_labels.csv
Organizes panels by metric type/category with hierarchical grouping
"""

import csv
import json
from pathlib import Path
from collections import defaultdict

# Paths (relative to this script's location)
SCRIPT_DIR = Path(__file__).parent
METRICS_CSV = SCRIPT_DIR / "../logs/pcp_parser/metrics_labels.csv"
OUTPUT_DASHBOARD = SCRIPT_DIR / "provisioning/dashboards/json/pcp-auto-dashboard.json"

def categorize_metric(metric_name):
    """Categorize metric into top-level group and subcategory"""
    parts = metric_name.split('.')

    if len(parts) >= 1:
        top_level = parts[0]  # e.g., 'kernel', 'disk', 'mem'

        # More specific subcategorization
        if len(parts) >= 2:
            subcategory = f"{parts[0]}.{parts[1]}"
            return top_level, subcategory

        return top_level, top_level

    return "other", "other"

def load_metrics(csv_path):
    """Load metrics from CSV and organize hierarchically"""
    # Structure: {top_level: {subcategory: [metrics]}}
    metrics_hierarchy = defaultdict(lambda: defaultdict(list))

    with open(csv_path, 'r', newline='') as f:
        reader = csv.reader(f)
        next(reader)  # Skip header

        for row in reader:
            if row:
                metric_name = row[0]
                top_level, subcategory = categorize_metric(metric_name)
                metrics_hierarchy[top_level][subcategory].append(metric_name)

    return metrics_hierarchy

def create_panel(panel_id, title, metrics, x, y, w=12, h=8):
    """Create a Grafana panel for a group of metrics"""

    # Convert metric names to field names (replace dots, dashes, and spaces with underscores)
    field_names = [m.replace('.', '_').replace('-', '_').replace(' ', '_') for m in metrics]

    # Build field filter regex
    if len(field_names) == 1:
        field_filter = f'r["_field"] == "{field_names[0]}"'
    else:
        # Create regex pattern for multiple fields - underscores don't need escaping in Flux regex
        field_pattern = "|".join(field_names)
        field_filter = f'r["_field"] =~ /^({field_pattern})$/'

    query = f"""from(bucket: "pcp-metrics")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "pcp_metrics")
  |> filter(fn: (r) => r["product_type"] =~ /${{product_type}}/)
  |> filter(fn: (r) => r["serialNumber"] =~ /${{serialNumber}}/)
  |> filter(fn: (r) => {field_filter})
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)"""

    panel = {
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
                    "showPoints": "never"
                }
            }
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
                "displayMode": "table" if len(metrics) > 5 else "list",
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
                "query": query,
                "refId": "A"
            }
        ],
        "title": title,
        "type": "timeseries"
    }

    return panel

def create_row(row_id, title, y, collapsed=True):
    """Create a collapsible row header"""
    return {
        "collapsed": collapsed,
        "gridPos": {
            "h": 1,
            "w": 24,
            "x": 0,
            "y": y
        },
        "id": row_id,
        "panels": [],
        "title": title,
        "type": "row"
    }

def generate_dashboard(metrics_hierarchy):
    """Generate complete Grafana dashboard JSON with hierarchical organization"""

    panels = []
    panel_id = 1
    y_position = 0

    # Sort top-level groups alphabetically
    sorted_groups = sorted(metrics_hierarchy.items())

    for top_level, subcategories in sorted_groups:
        # Calculate total metrics in this top-level group
        total_metrics = sum(len(metrics) for metrics in subcategories.values())
        num_subcategories = len(subcategories)

        # Create top-level group row (collapsed by default)
        group_row = create_row(
            panel_id,
            f"[{top_level.upper()}] - {num_subcategories} subcategories, {total_metrics} metrics",
            y_position,
            collapsed=True
        )
        group_row_panels = []  # Panels that belong to this group row
        panel_id += 1

        # Sort subcategories alphabetically
        sorted_subcategories = sorted(subcategories.items())

        subcat_y_position = 0  # Reset Y position for nested panels

        for subcategory, metrics in sorted_subcategories:
            if not metrics:
                continue

            # Grafana doesn't support nested rows, so we'll just add panels directly
            # with clear titles that show the subcategory

            # Group metrics into panels (max 10 metrics per panel for readability)
            metrics_per_panel = 10
            num_panels = (len(metrics) + metrics_per_panel - 1) // metrics_per_panel

            for i in range(num_panels):
                start_idx = i * metrics_per_panel
                end_idx = min(start_idx + metrics_per_panel, len(metrics))
                panel_metrics = metrics[start_idx:end_idx]

                # Calculate position (2 panels per row)
                x = 0 if i % 2 == 0 else 12
                if i % 2 == 0 and i > 0:
                    subcat_y_position += 8

                # Panel title shows subcategory clearly
                if num_panels > 1:
                    panel_title = f"[{subcategory}] Metrics {start_idx+1}-{end_idx} of {len(metrics)}"
                else:
                    panel_title = f"[{subcategory}] ({len(metrics)} metrics)"

                panel = create_panel(panel_id, panel_title, panel_metrics, x, subcat_y_position)
                group_row_panels.append(panel)  # Add directly to group row panels
                panel_id += 1

            # Move to next row after panels
            subcat_y_position += 8

        # Add all subcategory rows to the group row
        group_row["panels"] = group_row_panels
        panels.append(group_row)
        y_position += 1

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
        "panels": panels,
        "refresh": "",
        "schemaVersion": 38,
        "style": "dark",
        "tags": ["auto-generated", "pcp", "metrics", "hierarchical"],
        "templating": {
            "list": [
                {
                    "allValue": ".*",
                    "current": {
                        "selected": True,
                        "text": "All",
                        "value": "$__all"
                    },
                    "datasource": {
                        "type": "influxdb",
                        "uid": "influxdb"
                    },
                    "definition": "import \"influxdata/influxdb/v1\" v1.tagValues(bucket: \"pcp-metrics\", tag: \"product_type\", start: -30d)",
                    "hide": 0,
                    "includeAll": True,
                    "label": "Product Type",
                    "multi": False,
                    "name": "product_type",
                    "options": [],
                    "query": "import \"influxdata/influxdb/v1\" v1.tagValues(bucket: \"pcp-metrics\", tag: \"product_type\", start: -30d)",
                    "refresh": 2,
                    "regex": "",
                    "skipUrlSync": False,
                    "sort": 0,
                    "type": "query"
                },
                {
                    "allValue": ".*",
                    "current": {
                        "selected": True,
                        "text": "All",
                        "value": "$__all"
                    },
                    "datasource": {
                        "type": "influxdb",
                        "uid": "influxdb"
                    },
                    "definition": "import \"influxdata/influxdb/v1\" v1.tagValues(bucket: \"pcp-metrics\", tag: \"serialNumber\", start: -30d)",
                    "hide": 0,
                    "includeAll": True,
                    "label": "Serial Number",
                    "multi": False,
                    "name": "serialNumber",
                    "options": [],
                    "query": "import \"influxdata/influxdb/v1\" v1.tagValues(bucket: \"pcp-metrics\", tag: \"serialNumber\", start: -30d)",
                    "refresh": 2,
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
        "timezone": "browser",
        "title": "PCP Auto-Generated Metrics Dashboard (Hierarchical)",
        "uid": "pcp-auto-metrics",
        "version": 1,
        "weekStart": ""
    }

    return dashboard

def main():
    print("Loading metrics from CSV...")
    metrics_hierarchy = load_metrics(METRICS_CSV)

    # Calculate totals
    total_metrics = sum(
        sum(len(metrics) for metrics in subcats.values())
        for subcats in metrics_hierarchy.values()
    )
    total_groups = len(metrics_hierarchy)
    total_subcats = sum(len(subcats) for subcats in metrics_hierarchy.values())

    print(f"Found {total_metrics} metrics in {total_groups} top-level groups and {total_subcats} subcategories")

    # Print hierarchy summary
    print("\nMetrics hierarchy:")
    for top_level, subcategories in sorted(metrics_hierarchy.items()):
        subcat_count = len(subcategories)
        metric_count = sum(len(m) for m in subcategories.values())
        print(f"  [{top_level}]: {subcat_count} subcategories, {metric_count} metrics")
        for subcategory, metrics in sorted(subcategories.items()):
            print(f"    - {subcategory}: {len(metrics)} metrics")

    print(f"\nGenerating hierarchical dashboard...")
    dashboard = generate_dashboard(metrics_hierarchy)

    # Ensure output directory exists
    OUTPUT_DASHBOARD.parent.mkdir(parents=True, exist_ok=True)

    # Write dashboard JSON
    with open(OUTPUT_DASHBOARD, 'w') as f:
        json.dump(dashboard, f, indent=2)

    print(f"\nDashboard created successfully: {OUTPUT_DASHBOARD}")
    print(f"Total panels: {len(dashboard['panels'])}")
    print(f"Structure: {total_groups} top-level groups -> {total_subcats} subcategories -> {total_metrics} metrics")

if __name__ == "__main__":
    main()
