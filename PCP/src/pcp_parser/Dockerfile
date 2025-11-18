FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    pcp \
    pcp-export-pcp2influxdb \
    python3 \
    python3-pip \
    curl \
    inotify-tools \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install \
    influxdb3-python \
    requests \
    pandas \
    numpy \
    pyarrow \
    # Optional: Install faster CSV parsing (if needed)
    # python-snappy \  # For compression support
    && pip3 cache purge

# Parser configuration - OPTIMIZED for high-throughput
ENV SAVE_CSV_OUTPUT=false
ENV USE_MEMORY_BUFFER=true
ENV INFLUX_BATCH_SIZE=200000
ENV ENABLE_PARALLEL_VALIDATION=true
ENV PARALLEL_VALIDATION_WORKERS=100
ENV ENABLE_LZ4_DECOMPRESSION=false
ENV ENABLE_STREAMING_PMREP=true
ENV ENABLE_PARALLEL_PMREP=false
ENV PARALLEL_PMREP_WORKERS=3

# InfluxDB 3 Core configuration
ENV INFLUXDB_DATABASE=pcp-metrics
ENV VALIDATION_BATCH_SIZE=500
ENV PROGRESS_LOG_INTERVAL=50
ENV SKIP_VALIDATION=false
ENV FORCE_REVALIDATE=false

# Metric category filters
ENV ENABLE_PROCESS_METRICS=false
ENV ENABLE_DISK_METRICS=true
ENV ENABLE_FILE_METRICS=false
ENV ENABLE_MEMORY_METRICS=true
ENV ENABLE_NETWORK_METRICS=true
ENV ENABLE_KERNEL_METRICS=true
ENV ENABLE_SWAP_METRICS=false
ENV ENABLE_NFS_METRICS=false

WORKDIR /app

# Copy parser scripts from the build context
COPY *.sh /app/
COPY *.py /app/
RUN chmod +x /app/*.sh /app/*.py 2>/dev/null || true

# Use Python script for parsing
CMD ["python3", "/app/pcp_parser.py"]