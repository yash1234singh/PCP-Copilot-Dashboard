#!/bin/bash

# PCP Parser Starter Script
# Reads .env file and starts only enabled parsers

set -e

# Load environment variables from .env
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
else
    echo "Error: .env file not found!"
    exit 1
fi

# Build profiles array based on .env configuration
PROFILES=()

if [ "${ENABLE_PYTHON_PARSER}" = "true" ]; then
    PROFILES+=("python-parser")
    echo "✓ Python parser enabled"
else
    echo "✗ Python parser disabled"
fi

if [ "${ENABLE_GO_PARSER}" = "true" ]; then
    PROFILES+=("go-parser")
    echo "✓ Go parser enabled"
else
    echo "✗ Go parser disabled"
fi

if [ "${ENABLE_RUST_PARSER}" = "true" ]; then
    PROFILES+=("rust-parser")
    echo "✓ Rust parser enabled"
else
    echo "✗ Rust parser disabled"
fi

# Check if at least one parser is enabled
if [ ${#PROFILES[@]} -eq 0 ]; then
    echo ""
    echo "ERROR: No parsers enabled!"
    echo "Please set at least one parser to 'true' in .env file:"
    echo "  ENABLE_PYTHON_PARSER=true"
    echo "  ENABLE_GO_PARSER=true"
    echo "  ENABLE_RUST_PARSER=true"
    exit 1
fi

# Build profile argument for docker-compose
PROFILE_ARGS=""
for profile in "${PROFILES[@]}"; do
    PROFILE_ARGS="$PROFILE_ARGS --profile $profile"
done

echo ""
echo "Starting containers with profiles: ${PROFILES[*]}"
echo "Command: docker-compose $PROFILE_ARGS up -d"
echo ""

# Start docker-compose with selected profiles
docker-compose $PROFILE_ARGS up -d

echo ""
echo "✓ Started successfully!"
echo ""
echo "Running containers:"
docker ps --filter "name=pcp_parser" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
