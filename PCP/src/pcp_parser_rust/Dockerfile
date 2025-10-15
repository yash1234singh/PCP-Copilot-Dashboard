# Multi-stage build for Rust PCP parser
# Use Ubuntu 24.04 which has GLIBC 2.39
FROM rust:latest AS builder

# Create app directory
WORKDIR /build

# Copy Cargo files
COPY Cargo.toml ./

# Copy source code
COPY src ./src

# Build release binary
RUN cargo build --release

# Stage 2: Runtime image - Ubuntu 24.04 has GLIBC 2.39
FROM ubuntu:24.04

# Install PCP tools and dependencies
RUN apt-get update && apt-get install -y \
    pcp \
    pcp-export-pcp2influxdb \
    curl \
    ca-certificates \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy binary from builder
COPY --from=builder /build/target/release/pcp_parser_rust /app/pcp_parser_rust

# Make binary executable
RUN chmod +x /app/pcp_parser_rust

# Set environment variables
ENV WATCH_DIR=/src/input/raw
ENV EXTRACT_DIR=/tmp/pcp_archives
ENV PROCESSED_DIR=/src/archive/processed
ENV FAILED_DIR=/src/archive/failed
ENV LOG_DIR=/src/logs/pcp_parser_rust
ENV INFLUXDB_URL=http://influxdb:8086
ENV INFLUXDB_ORG=pcp-org
ENV INFLUXDB_BUCKET=pcp-metrics
ENV INFLUXDB_TOKEN=pcp-admin-token-12345
ENV PRODUCT_TYPE=TEST_RUST_01
ENV SERIAL_NUMBER=12345
ENV RUST_LOG=info

# Create necessary directories
RUN mkdir -p /tmp/pcp_archives /src/logs/pcp_parser_rust

# Run the parser
CMD ["/app/pcp_parser_rust"]
