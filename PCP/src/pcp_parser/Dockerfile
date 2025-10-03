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

RUN pip3 install influxdb-client requests

WORKDIR /app

# Copy parser scripts from the build context
COPY *.sh /app/
COPY *.py /app/
RUN chmod +x /app/*.sh /app/*.py 2>/dev/null || true

# Use Python script for parsing
CMD ["python3", "/app/pcp_parser.py"]