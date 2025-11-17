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
    influxdb-client \
    requests \
    pandas \
    numpy \
    # Optional: Install faster CSV parsing (if needed)
    # python-snappy \  # For compression support
    # pyarrow \        # For faster parquet/dataframe operations
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

WORKDIR /app

# Copy parser scripts from the build context
COPY *.sh /app/
COPY *.py /app/
RUN chmod +x /app/*.sh /app/*.py 2>/dev/null || true

# Use Python script for parsing
CMD ["python3", "/app/pcp_parser.py"]