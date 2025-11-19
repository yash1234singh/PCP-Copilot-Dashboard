#!/bin/bash
#
# AWS S3 Write Test Script
#
# This script tests AWS S3 write functionality for PCP Parquet export
#
# Usage:
#   ./test_s3.sh                    # Run from host machine
#   docker exec pcp_parser_python python3 test_s3_write.py  # Run inside container
#

set -e

echo "========================================="
echo "AWS S3 Write Test"
echo "========================================="
echo ""

# Check if container is running
if ! docker ps | grep -q pcp_parser_python; then
    echo "⚠️  Container 'pcp_parser_python' is not running"
    echo "Starting container..."
    cd "$(dirname "$0")"
    docker-compose up -d pcp_parser_python
    echo "Waiting for container to be ready..."
    sleep 3
fi

echo "Running S3 write tests..."
echo ""

# Run the test script
docker exec pcp_parser_python python3 test_s3_write.py

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "✅ All tests passed successfully!"
else
    echo ""
    echo "❌ Some tests failed. Check output above for details."
fi

exit $EXIT_CODE
