# Parser Configuration Guide

## Overview

The PCP monitoring system supports three parser implementations:
- **Python Parser** (default, most stable)
- **Go Parser** (experimental, high performance)
- **Rust Parser** (experimental, memory safe)

By default, **only the Python parser runs**. You can enable/disable parsers via configuration.

---

## Configuration File: `.env`

All parser settings are controlled in the `.env` file:

```bash
# Parser Configuration - Set to 'true' to enable, 'false' to disable
ENABLE_PYTHON_PARSER=true   # Default: enabled
ENABLE_GO_PARSER=false      # Default: disabled
ENABLE_RUST_PARSER=false    # Default: disabled
```

---

## Starting Parsers

### Windows (Recommended)

```cmd
cd C:\Users\yashvardhan.singh\PycharmProjects\pythonProject2\PCP\src
start-parsers.bat
```

### Linux/Mac

```bash
cd /path/to/PCP/src
chmod +x start-parsers.sh
./start-parsers.sh
```

### Manual (Docker Compose)

```bash
# Python parser only (default)
docker-compose --profile python-parser up -d

# Python + Go parsers
docker-compose --profile python-parser --profile go-parser up -d

# All three parsers
docker-compose --profile python-parser --profile go-parser --profile rust-parser up -d
```

---

## Common Configurations

### 1. Default (Python Only)

**`.env` configuration:**
```bash
ENABLE_PYTHON_PARSER=true
ENABLE_GO_PARSER=false
ENABLE_RUST_PARSER=false
```

**Use case**: Production, stable, well-tested

**Command:**
```bash
start-parsers.bat
```

**Running containers:**
- `pcp_parser_python` ✓

---

### 2. Python + Go (Performance Testing)

**`.env` configuration:**
```bash
ENABLE_PYTHON_PARSER=true
ENABLE_GO_PARSER=true
ENABLE_RUST_PARSER=false
```

**Use case**: Compare performance between Python and Go implementations

**Command:**
```bash
start-parsers.bat
```

**Running containers:**
- `pcp_parser_python` ✓
- `pcp_parser_go` ✓

**Note**: Both parsers will process the same archives in parallel

---

### 3. All Parsers (Development/Testing)

**`.env` configuration:**
```bash
ENABLE_PYTHON_PARSER=true
ENABLE_GO_PARSER=true
ENABLE_RUST_PARSER=true
```

**Use case**: Development, benchmarking, feature comparison

**Command:**
```bash
start-parsers.bat
```

**Running containers:**
- `pcp_parser_python` ✓
- `pcp_parser_go` ✓
- `pcp_parser_rust` ✓

---

### 4. Go Parser Only (High Performance)

**`.env` configuration:**
```bash
ENABLE_PYTHON_PARSER=false
ENABLE_GO_PARSER=true
ENABLE_RUST_PARSER=false
```

**Use case**: Production with Go parser (after testing)

**Command:**
```bash
start-parsers.bat
```

**Running containers:**
- `pcp_parser_go` ✓

---

## Stopping Parsers

### Stop All

```bash
docker-compose down
```

### Stop Specific Parser

```bash
# Stop Python parser
docker stop pcp_parser_python

# Stop Go parser
docker stop pcp_parser_go

# Stop Rust parser
docker stop pcp_parser_rust
```

---

## Viewing Logs

### Python Parser

```bash
docker logs -f pcp_parser_python
```

### Go Parser

```bash
docker logs -f pcp_parser_go
```

### Rust Parser

```bash
docker logs -f pcp_parser_rust
```

### All Parsers

```bash
# Windows PowerShell
Get-ChildItem -Filter "pcp_parser_*" | ForEach-Object { docker logs --tail 50 $_.Name }

# Linux/Mac
docker ps --filter "name=pcp_parser" --format "{{.Names}}" | xargs -I {} docker logs --tail 50 {}
```

---

## Rebuilding Parsers

### Rebuild Specific Parser

```bash
# Python
docker-compose build pcp_parser_python

# Go
docker-compose build pcp_parser_go

# Rust
docker-compose build pcp_parser_rust
```

### Rebuild with No Cache

```bash
docker-compose build --no-cache pcp_parser_python
```

---

## Troubleshooting

### Error: "No parsers enabled!"

**Problem**: All parser flags are set to `false` in `.env`

**Solution**: Enable at least one parser:
```bash
ENABLE_PYTHON_PARSER=true
```

### Error: "Container already exists"

**Problem**: Container from previous run still exists

**Solution**:
```bash
docker-compose down
start-parsers.bat
```

### Parser Not Starting

**Problem**: Profile not specified or incorrect

**Check running containers**:
```bash
docker ps --filter "name=pcp_parser"
```

**Manual start with profile**:
```bash
docker-compose --profile python-parser up -d
```

### Code Changes Not Reflected

**Problem**: Docker using cached image

**Solution**: Rebuild with no cache
```bash
docker-compose down
docker-compose build --no-cache pcp_parser_python
start-parsers.bat
```

---

## Parser Comparison

| Feature | Python | Go | Rust |
|---------|--------|----|----|
| **Stability** | ✓✓✓ High | ✓✓ Medium | ✓ Low |
| **Performance** | ✓ 1x baseline | ✓✓✓ 3-5x faster | ✓✓✓ 3-5x faster |
| **Memory Usage** | ✓✓ Medium | ✓✓✓ Low | ✓✓✓ Very Low |
| **Features** | ✓✓✓ Complete | ✓✓ Most | ✓ Basic |
| **Maintenance** | ✓✓✓ Active | ✓✓ Active | ✓ Experimental |
| **Production Ready** | ✓✓✓ Yes | ✓ Beta | ✗ No |

---

## Architecture

### How Profiles Work

Docker Compose profiles allow selective service startup:

```yaml
# docker-compose.yml
services:
  pcp_parser_python:
    profiles:
      - python-parser    # Only starts with --profile python-parser
    ...

  pcp_parser_go:
    profiles:
      - go-parser        # Only starts with --profile go-parser
    ...
```

When you run `docker-compose up -d` without profiles, **no parsers start**.

When you run `docker-compose --profile python-parser up -d`, **only Python parser starts**.

The `start-parsers.bat` script reads `.env` and automatically adds the correct profiles.

---

## Log Directory Structure

Each parser has its own log directory:

```
/src/logs/
├── pcp_parser_python/
│   ├── pcp_parser.log
│   └── pmrep_output_*.csv (if CSV enabled)
├── pcp_parser_go/
│   ├── pcp_parser.log
│   └── pmrep_output_*.csv (if CSV enabled)
└── pcp_parser_rust/
    ├── pcp_parser.log
    └── pmrep_output_*.csv (if CSV enabled)
```

---

## Archive Processing

### Parallel Processing

When multiple parsers are enabled, they process archives **in parallel**:

1. Archive arrives in `/src/input/raw/`
2. All enabled parsers detect it simultaneously
3. Each parser:
   - Extracts archive to its own temp directory
   - Processes metrics
   - Exports to InfluxDB
4. First parser to complete moves archive to `/src/archive/processed/`
5. Other parsers skip the moved archive

### Coordination

Parsers coordinate using:
- **File locks**: Prevent simultaneous processing
- **Parser ID**: Each parser has unique identifier (`PARSER_ID` env var)
- **Processed directory**: Shared success indicator

---

## Environment Variables

Each parser respects these `.env` variables:

```bash
# System Identification
PRODUCT_TYPE=SW_DEV_06
SERIAL_NUMBER=123455

# Parser Enable/Disable
ENABLE_PYTHON_PARSER=true
ENABLE_GO_PARSER=false
ENABLE_RUST_PARSER=false

# InfluxDB Configuration (shared by all parsers)
INFLUXDB_URL=http://influxdb:8086
INFLUXDB_TOKEN=pcp-admin-token-12345
INFLUXDB_ORG=pcp-org
INFLUXDB_BUCKET=pcp-metrics

# Processing Options (override in docker-compose.yml per parser)
SAVE_CSV_OUTPUT=false
USE_MEMORY_BUFFER=false
```

---

## Quick Reference

### Start Only Python Parser (Default)

```bash
# Edit .env
ENABLE_PYTHON_PARSER=true
ENABLE_GO_PARSER=false
ENABLE_RUST_PARSER=false

# Start
start-parsers.bat
```

### Start Python + Go Parsers

```bash
# Edit .env
ENABLE_PYTHON_PARSER=true
ENABLE_GO_PARSER=true
ENABLE_RUST_PARSER=false

# Start
start-parsers.bat
```

### Check What's Running

```bash
docker ps --filter "name=pcp_parser"
```

### View Logs

```bash
docker logs -f pcp_parser_python
```

### Stop Everything

```bash
docker-compose down
```

### Rebuild and Restart

```bash
docker-compose down
docker-compose build pcp_parser_python
start-parsers.bat
```

---

## Best Practices

1. **Production**: Use Python parser only (`ENABLE_PYTHON_PARSER=true`, others `false`)
2. **Development**: Enable all parsers for testing
3. **Performance Testing**: Enable Python + one other for comparison
4. **Always check logs** after starting: `docker logs -f pcp_parser_python`
5. **Rebuild after code changes**: `docker-compose build pcp_parser_python`
6. **Use `start-parsers.bat`** instead of manual docker-compose commands

---

## Examples

### Example 1: Fresh Start with Python Parser

```bash
cd C:\Users\yashvardhan.singh\PycharmProjects\pythonProject2\PCP\src

# Ensure .env has Python enabled
echo ENABLE_PYTHON_PARSER=true > .env.tmp
echo ENABLE_GO_PARSER=false >> .env.tmp
echo ENABLE_RUST_PARSER=false >> .env.tmp

# Stop any running containers
docker-compose down

# Start with configuration
start-parsers.bat

# Verify
docker ps --filter "name=pcp_parser"
```

### Example 2: Switch from Python to Go

```bash
# Stop current parser
docker-compose down

# Edit .env
ENABLE_PYTHON_PARSER=false
ENABLE_GO_PARSER=true

# Start new parser
start-parsers.bat
```

### Example 3: Run All Parsers for Benchmark

```bash
# Edit .env
ENABLE_PYTHON_PARSER=true
ENABLE_GO_PARSER=true
ENABLE_RUST_PARSER=true

# Start all
start-parsers.bat

# Monitor all logs
docker-compose logs -f pcp_parser_python pcp_parser_go pcp_parser_rust
```
