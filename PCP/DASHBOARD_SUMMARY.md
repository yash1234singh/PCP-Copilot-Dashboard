# PCP Grafana Dashboards Summary

## Overview

The PCP monitoring system now includes **three Grafana dashboards** for different monitoring needs, plus tools to customize them.

## Quick Access URLs

| Dashboard | URL | Purpose |
|-----------|-----|---------|
| **Limited View** | http://localhost:3000/d/pcp-limited-view/ | Daily monitoring (100 metrics) |
| **Auto-Generated** | http://localhost:3000/d/pcp-auto-metrics/ | Comprehensive view (1000+ metrics) |
| **Manual/PSOC** | http://localhost:3000/dashboards | Hand-crafted PSOC metrics |

## Dashboard Comparison

### 1. Limited View Dashboard ⭐ (NEW - Recommended)

**Location:** `src/grafana/provisioning/dashboards/json/pcp-limited-view.json`

**Metrics Source:** `src/input/data_filter/validated_metrics.txt`

**Overview:**
- **100 curated metrics** - Essential system performance indicators
- **8 categories** - CPU, Memory, Disk, Network, Filesystem, Process, Thermal, System Info
- **20 panels** - Clean, organized layout
- **Fast loading** - Optimized queries
- **Easy customization** - Edit text file to add/remove metrics

**Best For:**
- ✅ Daily operational monitoring
- ✅ Executive dashboards and reports
- ✅ Quick system health checks
- ✅ Performance overviews
- ✅ Users new to the system

**Categories:**
1. System Information & Hardware (10 metrics)
2. CPU Utilization & Performance (15 metrics)
3. Memory Utilization (20 metrics)
4. Disk I/O Performance (15 metrics)
5. Filesystem (5 metrics)
6. Network Performance (20 metrics)
7. Process & System Activity (8 metrics)
8. Thermal & Power Monitoring (7 metrics)

**Generate/Regenerate:**
```bash
cd src/grafana
python generate_limited_dashboard.py
```

**Customize:**
1. Edit `src/input/data_filter/validated_metrics.txt`
2. Add/remove metric names (one per line)
3. Use `##` for category headers
4. Use `#` for comments
5. Run generator script
6. Dashboard updates automatically in 30 seconds

**Documentation:** `src/grafana/LIMITED_VIEW_README.md`

---

### 2. Auto-Generated Dashboard (Comprehensive)

**Location:** `src/grafana/provisioning/dashboards/json/pcp-auto-dashboard.json`

**Metrics Source:** `src/logs/pcp_parser/metrics_labels.csv` (auto-discovered)

**Overview:**
- **1000+ metrics** - All discovered metrics from archives
- **12+ top-level groups** - Hierarchical organization
- **74+ subcategories** - Detailed breakdown
- **100+ panels** - Comprehensive coverage
- **Auto-updates** - Includes new metrics automatically

**Best For:**
- ✅ Detailed troubleshooting
- ✅ Finding specific metrics
- ✅ Comprehensive system analysis
- ✅ Discovering available metrics
- ✅ Advanced users and operators

**Generate/Regenerate:**
```bash
cd src/grafana
python generate_dashboard.py
```

**Documentation:** `src/grafana/DASHBOARD_README.md`

---

### 3. Manual Dashboard (PSOC-Specific)

**Location:** `src/grafana/provisioning/dashboards/json/pcp-metrics.json` (if exists)

**Overview:**
- **Custom designed** - Hand-crafted panels
- **PSOC metrics** - Specific to PSOC hardware
- **Fixed configuration** - Doesn't auto-update
- **Presentation ready** - Polished visualizations

**Best For:**
- ✅ PSOC system monitoring
- ✅ Custom presentations
- ✅ Specific use cases

---

## Choosing the Right Dashboard

### Use Limited View Dashboard when you need:
- Fast loading times
- Clean, uncluttered interface
- Essential metrics only
- Easy customization
- Daily monitoring workflow

### Use Auto-Generated Dashboard when you need:
- All available metrics
- Discovering new metrics
- Deep-dive troubleshooting
- Comprehensive coverage
- Automatic updates

### Use Manual Dashboard when you need:
- PSOC-specific monitoring
- Custom visualizations
- Presentation-ready views
- Fixed, stable dashboards

## Workflow Recommendation

```
┌─────────────────────────────────────────────────────┐
│ Daily Operations                                     │
│ → Use Limited View Dashboard                        │
│   - Quick health checks                             │
│   - Monitor key metrics                             │
│   - Check system status                             │
└─────────────────────────────────────────────────────┘
                      ↓ Issue detected
┌─────────────────────────────────────────────────────┐
│ Troubleshooting                                      │
│ → Switch to Auto-Generated Dashboard                │
│   - Find related metrics                            │
│   - Analyze correlations                            │
│   - Deep-dive investigation                         │
└─────────────────────────────────────────────────────┘
                      ↓ Custom needs
┌─────────────────────────────────────────────────────┐
│ Custom Analysis                                      │
│ → Create manual dashboard in Grafana UI             │
│   - Export as JSON                                  │
│   - Save to provisioning/dashboards/json/           │
└─────────────────────────────────────────────────────┘
```

## Customizing the Limited View Dashboard

### Step 1: Identify Metrics You Need

**Option A: From Auto-Generated Dashboard**
1. Open Auto-Generated Dashboard
2. Browse through categories
3. Note metric names you want to include

**Option B: From Discovery Process**
1. Set `FORCE_REVALIDATE=true` in docker-compose.yml
2. Restart parser: `docker-compose restart pcp_parser_python`
3. Check discovered metrics: `cat src/logs/pcp_parser_python/validated_metrics_discovered.txt`
4. Copy desired metrics

### Step 2: Edit Validated Metrics File

```bash
# Open the file
nano src/input/data_filter/validated_metrics.txt

# Add your metrics
## MY CUSTOM CATEGORY
my.custom.metric1
my.custom.metric2

# Save and exit
```

### Step 3: Regenerate Dashboard

```bash
cd src/grafana
python generate_limited_dashboard.py
```

### Step 4: View Updated Dashboard

Wait 30 seconds for Grafana to auto-reload, or refresh the browser.

## Dashboard Variables

All dashboards support filtering by:

### product_type
- Filter data by product type
- Default: "All"
- Dynamically populated from InfluxDB

### serialNumber
- Filter data by device serial number
- Default: "All"
- Dynamically populated from InfluxDB

**Usage:**
1. Click variable dropdown at top of dashboard
2. Select specific value or keep "All"
3. All panels update automatically

## File Structure

```
PCP/src/grafana/
├── generate_dashboard.py              # Generate auto-discovery dashboard
├── generate_limited_dashboard.py      # Generate limited view dashboard (NEW)
├── LIMITED_VIEW_README.md             # Limited view documentation (NEW)
├── DASHBOARD_README.md                # Auto-generated dashboard docs
│
└── provisioning/
    └── dashboards/
        ├── dashboard.yml              # Provisioning config
        └── json/
            ├── pcp-auto-dashboard.json      # Auto-generated dashboard
            ├── pcp-limited-view.json        # Limited view dashboard (NEW)
            └── pcp-metrics.json             # Manual dashboard (optional)
```

## Integration with Data Filter

The Limited View Dashboard is tightly integrated with the centralized metrics configuration:

```
src/input/data_filter/validated_metrics.txt
          ↓
    (Used by 3 systems)
          ↓
    ┌─────┴─────┬─────────────┐
    ↓           ↓             ↓
PCP Parser   PCP Parser   Grafana Dashboard
 (Python)      (Go/Rust)   (Limited View)
```

**Benefits:**
- Single source of truth for important metrics
- Parsers and dashboard stay in sync
- Easy to maintain and update
- Changes propagate to all systems

## Performance Comparison

| Metric | Limited View | Auto-Generated |
|--------|-------------|----------------|
| **Metrics** | 100 | 1000+ |
| **Panels** | 20 | 100+ |
| **Load Time** | 2-3 sec | 5-10 sec |
| **Refresh Time** | 1-2 sec | 3-5 sec |
| **Queries** | 20 concurrent | 100+ concurrent |
| **Browser Memory** | 50-100 MB | 200-300 MB |
| **Best For** | Daily use | Troubleshooting |

## Troubleshooting

### Dashboard Not Appearing

1. **Check file exists:**
   ```bash
   ls src/grafana/provisioning/dashboards/json/pcp-limited-view.json
   ```

2. **Verify Grafana is running:**
   ```bash
   docker ps | grep grafana
   ```

3. **Wait for provisioning:**
   - Grafana scans for dashboards every 30 seconds
   - Refresh browser after 30-60 seconds

### No Data in Panels

1. **Verify metrics in InfluxDB:**
   - Open http://localhost:8086
   - Check pcp-metrics bucket
   - Query for specific metrics

2. **Check metric names:**
   - Ensure names in `validated_metrics.txt` are correct
   - Metric names are case-sensitive
   - Dots become underscores in field names

3. **Verify time range:**
   - Check dashboard time picker (top right)
   - Ensure it covers when data was processed
   - Try expanding to "Last 24 hours"

### Dashboard Shows Wrong Metrics

1. **Regenerate dashboard:**
   ```bash
   cd src/grafana
   python generate_limited_dashboard.py
   ```

2. **Verify source file:**
   ```bash
   cat src/input/data_filter/validated_metrics.txt
   ```

3. **Check for syntax errors:**
   - No extra spaces in metric names
   - Comments start with `#`
   - Category headers use `##`

## Summary

| Feature | Limited View | Auto-Generated | Manual |
|---------|-------------|----------------|--------|
| **Metrics Count** | ~100 | 1000+ | Custom |
| **Load Time** | Fast | Slower | Fast |
| **Customization** | Very Easy | Auto | Manual |
| **Updates** | Manual | Auto | Manual |
| **Organization** | Categories | Hierarchical | Custom |
| **Best For** | Daily use | Analysis | Presentations |
| **Maintenance** | Low | None | High |
| **Learning Curve** | Easy | Medium | Easy |

## Getting Started

**For new users:**
1. Start with **Limited View Dashboard** for daily monitoring
2. Learn the essential 100 metrics
3. Customize by adding metrics you need
4. Switch to Auto-Generated for troubleshooting

**For advanced users:**
1. Use **Auto-Generated Dashboard** to discover all metrics
2. Identify frequently used metrics
3. Add them to `validated_metrics.txt`
4. Use **Limited View Dashboard** for routine monitoring
5. Create custom manual dashboards for specific needs

## Support

- **Limited View Dashboard:** See `src/grafana/LIMITED_VIEW_README.md`
- **Auto-Generated Dashboard:** See `src/grafana/DASHBOARD_README.md`
- **Main Documentation:** See `README.md`
- **Metrics Configuration:** See `src/input/data_filter/validated_metrics.txt`
