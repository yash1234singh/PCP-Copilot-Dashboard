# Dashboard Provisioning

## Issue
The dashboard was causing Grafana to restart constantly due to datasource validation errors during provisioning.

## Temporary Fix
The dashboard JSON file has been moved to `json_disabled/` directory to allow Grafana to start successfully.

## To Re-enable the Dashboard
Once Grafana is running and stable:

1. Move the dashboard back:
   ```bash
   mv json_disabled/system-metrics.json json/
   ```

2. Or manually import the dashboard via Grafana UI:
   - Go to http://localhost:3000
   - Login (admin/admin)
   - Navigate to Dashboards → Import
   - Upload `json_disabled/system-metrics.json`

## Permanent Solution
The dashboard will auto-load once the datasource is properly configured and Grafana is stable.
