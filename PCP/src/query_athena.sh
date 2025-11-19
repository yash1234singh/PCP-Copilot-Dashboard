#!/bin/bash
#
# AWS Athena Query Script for PCP Metrics
#
# Complete workflow: Setup → Query → Export
#
# Usage:
#   ./query_athena.sh                                    # Query last 7 days (auto-setup if needed)
#   ./query_athena.sh --setup-only                       # Just setup database/table
#   ./query_athena.sh --start-time "2025-11-01 00:00:00" # Custom time range
#   ./query_athena.sh --output results.csv               # Export to CSV
#   ./query_athena.sh --check-permissions                # Check IAM permissions
#   ./query_athena.sh --help                             # Show help
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print colored message
print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_header() {
    echo ""
    echo "========================================="
    echo "$1"
    echo "========================================="
    echo ""
}

# Check if permission check is requested
if [[ "$1" == "--check-permissions" ]]; then
    print_header "AWS Athena Permissions Checker"

    # Check if container is running
    if ! docker ps | grep -q pcp_parser_python; then
        print_warning "Container 'pcp_parser_python' is not running"
        print_info "Starting container..."
        cd "$SCRIPT_DIR"
        docker-compose up -d pcp_parser_python
        print_info "Waiting for container to be ready..."
        sleep 3
        echo ""
    fi

    # Copy query script (includes permission checker)
    docker cp "$SCRIPT_DIR/pcp_parser/query_athena.py" pcp_parser_python:/app/query_athena.py 2>/dev/null || true

    # Run permission check
    docker exec pcp_parser_python python3 query_athena.py --check-permissions
    exit $?
fi

print_header "AWS Athena Query for PCP Metrics"

# Check if help is requested
if [[ "$1" == "--help" ]] || [[ "$1" == "-h" ]]; then
    echo "Usage: ./query_athena.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --setup-only                    Setup database/table only, skip query"
    echo "  --check-permissions             Check AWS IAM permissions"
    echo "  --start-time \"YYYY-MM-DD HH:MM:SS\"  Start time filter"
    echo "  --end-time \"YYYY-MM-DD HH:MM:SS\"    End time filter"
    echo "  --product-type TYPE             Product type filter"
    echo "  --serial-number NUMBER          Serial number filter"
    echo "  --limit N                       Max rows to return (default: 1000)"
    echo "  --output FILE.csv               Export to CSV"
    echo "  --summary-only                  Show summary statistics only"
    echo "  --help, -h                      Show this help"
    echo ""
    echo "Examples:"
    echo "  ./query_athena.sh                                    # Query last 7 days"
    echo "  ./query_athena.sh --setup-only                       # Setup only"
    echo "  ./query_athena.sh --check-permissions                # Check permissions"
    echo "  ./query_athena.sh --start-time \"2025-11-01 00:00:00\" # Custom time"
    echo "  ./query_athena.sh --output results.csv               # Export to CSV"
    echo ""
    echo "Documentation:"
    echo "  See pcp_parser/ATHENA_README.md for complete guide"
    exit 0
fi

# Step 1: Check if container is running
print_info "Checking Docker container..."
if ! docker ps | grep -q pcp_parser_python; then
    print_warning "Container 'pcp_parser_python' is not running"
    print_info "Starting container..."
    cd "$SCRIPT_DIR"
    docker-compose up -d pcp_parser_python
    print_info "Waiting for container to be ready..."
    sleep 3
    print_success "Container started"
else
    print_success "Container is running"
fi
echo ""

# Step 2: Copy script to container
print_info "Preparing Athena query script..."
docker cp "$SCRIPT_DIR/pcp_parser/query_athena.py" pcp_parser_python:/app/query_athena.py 2>/dev/null || {
    print_error "Failed to copy query script"
    exit 1
}
print_success "Script ready"
echo ""

# Step 3: Check AWS credentials
print_info "Verifying AWS credentials..."
CREDS_CHECK=$(docker exec pcp_parser_python python3 -c "
import os
access_key = os.getenv('AWS_ACCESS_KEY_ID')
secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
if access_key and secret_key:
    print('OK')
else:
    print('MISSING')
" 2>/dev/null || echo "ERROR")

if [[ "$CREDS_CHECK" == "OK" ]]; then
    print_success "AWS credentials found"
elif [[ "$CREDS_CHECK" == "MISSING" ]]; then
    print_error "AWS credentials not found in .env file"
    echo ""
    echo "Please add these to src/.env:"
    echo "  AWS_ACCESS_KEY_ID=your-access-key"
    echo "  AWS_SECRET_ACCESS_KEY=your-secret-key"
    echo ""
    exit 1
else
    print_warning "Could not verify credentials (continuing anyway)"
fi
echo ""

# Step 4: Quick permission check (optional, non-blocking)
if [[ "$1" != "--setup-only" ]]; then
    print_info "Quick permission check..."
    PERM_CHECK=$(docker exec pcp_parser_python python3 -c "
import boto3
try:
    s3 = boto3.client('s3', region_name='us-west-2')
    s3.head_bucket(Bucket='fst-pcp-data1')
    print('OK')
except Exception as e:
    print('WARN')
" 2>/dev/null || echo "ERROR")

    if [[ "$PERM_CHECK" == "OK" ]]; then
        print_success "S3 bucket accessible"
    elif [[ "$PERM_CHECK" == "WARN" ]]; then
        print_warning "S3 access issue (will try to continue)"
        print_info "Run './query_athena.sh --check-permissions' for detailed check"
    fi
    echo ""
fi

# Step 5: Run Athena query
print_header "Executing Athena Query"

docker exec pcp_parser_python python3 query_athena.py "$@"

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    print_success "Query completed successfully!"
    echo ""
    echo "Next steps:"
    echo "  - Run queries with different time ranges"
    echo "  - Export to CSV: ./query_athena.sh --output results.csv"
    echo "  - See documentation: pcp_parser/ATHENA_README.md"
else
    print_error "Query failed"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check permissions: ./query_athena.sh --check-permissions"
    echo "  2. Verify IAM policy: See pcp_parser/ATHENA_README.md"
    echo "  3. Check if data exists in S3: s3://fst-pcp-data1/"
    echo ""
    echo "If you get 'AccessDenied' errors:"
    echo "  - You need to add Athena/Glue IAM permissions"
    echo "  - See ATHENA_README.md section 'Required IAM Permissions'"
fi

exit $EXIT_CODE
