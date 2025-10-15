# Build stage
FROM golang:1.21-alpine AS builder

# Install build dependencies
RUN apk add --no-cache git

WORKDIR /build

# Copy go mod and source files
COPY go.mod main.go ./

# Download dependencies and tidy
RUN go mod download && go mod tidy

# Build the application
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o pcp_parser .

# Runtime stage
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install PCP tools and dependencies
RUN apt-get update && apt-get install -y \
    pcp \
    pcp-export-pcp2influxdb \
    curl \
    ca-certificates \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the binary from builder
COPY --from=builder /build/pcp_parser /app/pcp_parser

# Make it executable
RUN chmod +x /app/pcp_parser

# Run the application
CMD ["/app/pcp_parser"]
