#!/usr/bin/env python3
"""
PCP Parser Log Analysis Tool
Parses pcp_parser.log and generates detailed performance statistics with histograms
Supports multi-file comparison for before/after optimization analysis
"""

import re
import sys
import argparse
from pathlib import Path
from collections import defaultdict, Counter
import statistics
import csv

try:
    import matplotlib.pyplot as plt
    import matplotlib
    matplotlib.use('Agg')  # Use non-interactive backend
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("[WARNING] matplotlib not installed - visual histograms will be skipped")
    print("Install with: pip install matplotlib")
    print()

# Default configuration
DEFAULT_LOG_FILE = Path("src/logs/pcp_parser_python/pcp_parser.log")


class PCPLogAnalyzer:
    def __init__(self, log_file):
        self.log_file = log_file
        self.archives = []
        self.current_archive = {}
        self.errors = []  # Store all errors found
        self.error_patterns = {
            'connection_error': [
                r'Connection refused',
                r'Connection timeout',
                r'Unable to connect',
                r'Network unreachable'
            ],
            'permission_error': [
                r'Permission denied',
                r'Access denied',
                r'Insufficient permissions'
            ],
            'file_error': [
                r'File not found',
                r'No such file or directory',
                r'Cannot open file',
                r'Failed to read file'
            ],
            'parsing_error': [
                r'Failed to parse',
                r'Invalid format',
                r'Parsing failed',
                r'Malformed data'
            ],
            'database_error': [
                r'InfluxDB.*error',
                r'Database.*error',
                r'Failed to write to database',
                r'Connection to.*failed'
            ],
            'validation_error': [
                r'Validation failed',
                r'Invalid metric',
                r'Metric.*not found'
            ],
            'extraction_error': [
                r'Failed to extract',
                r'Extraction.*failed',
                r'tar.*error'
            ],
            'pmrep_error': [
                r'pmrep.*error',
                r'pmrep.*failed',
                r'PCP.*error'
            ]
        }

    def parse_log(self):
        """Parse the log file and extract all archive processing data"""
        print(f"Parsing log file: {self.log_file}")
        print(f"File size: {self.log_file.stat().st_size / (1024*1024):.2f} MB")
        print()

        with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line_num, line in enumerate(f, 1):
                self._process_line(line)

                # Progress indicator
                if line_num % 10000 == 0:
                    print(f"\rProcessed {line_num:,} lines...", end='', flush=True)

        # Add last archive if exists
        if self.current_archive.get('archive'):
            self.archives.append(self.current_archive)

        print(f"\r[OK] Parsed {line_num:,} lines")
        print(f"[OK] Found {len(self.archives)} archives")
        print()

    def _process_line(self, line):
        """Process a single log line"""
        # Extract errors and warnings
        self._extract_errors(line)

        # New archive starts
        if 'Processing archive:' in line:
            # Save previous archive
            if self.current_archive.get('archive'):
                self.archives.append(self.current_archive)

            # Start new archive
            match = re.search(r'Processing archive: (.+\.tar\.xz)', line)
            if match:
                self.current_archive = {
                    'archive': match.group(1),
                    'extraction': 0,
                    'validation': 0,
                    'export': 0,
                    'total_time': 0,
                    'points': 0,
                    'lines': 0
                }

        # Extract timing data
        if not self.current_archive.get('archive'):
            return

        # Extraction time
        if '├─ Extraction:' in line or 'Extracted in' in line:
            match = re.search(r'([\d.]+)s', line)
            if match:
                self.current_archive['extraction'] = float(match.group(1))

        # Validation time
        if '├─ Validation:' in line or 'Metric validation completed in' in line:
            match = re.search(r'([\d.]+)', line)
            if match:
                self.current_archive['validation'] = float(match.group(1))

        # Export time
        if '└─ Export:' in line or 'InfluxDB export completed in' in line:
            match = re.search(r'([\d.]+)', line)
            if match:
                self.current_archive['export'] = float(match.group(1))

        # Total time
        if 'TOTAL PROCESSING TIME:' in line:
            match = re.search(r'(\d+) minutes ([\d.]+) seconds', line)
            if match:
                minutes = int(match.group(1))
                seconds = float(match.group(2))
                self.current_archive['total_time'] = minutes * 60 + seconds

        # Data points
        if 'Total data points written:' in line:
            match = re.search(r'Total data points written: (\d+)', line)
            if match:
                self.current_archive['points'] = int(match.group(1))

        # Lines processed
        if 'Processed' in line and 'lines from pmrep' in line:
            match = re.search(r'Processed (\d+) lines', line)
            if match:
                self.current_archive['lines'] = int(match.group(1))

    def _extract_errors(self, line):
        """Extract and categorize errors from log line"""
        line_lower = line.lower()

        # Check if line contains error/warning keywords
        if not any(keyword in line_lower for keyword in ['error', 'warning', 'failed', 'exception', 'traceback']):
            return

        # Categorize error
        error_type = 'unknown_error'
        for category, patterns in self.error_patterns.items():
            for pattern in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    error_type = category
                    break
            if error_type != 'unknown_error':
                break

        # Store error
        self.errors.append({
            'type': error_type,
            'message': line.strip(),
            'archive': self.current_archive.get('archive', 'Unknown')
        })

    def generate_statistics(self):
        """Generate comprehensive statistics"""
        if not self.archives:
            print("No archives found in log")
            return

        # Separate by type
        full_day = [a for a in self.archives if a['archive'].count('.') == 2]
        hourly = [a for a in self.archives if a['archive'].count('.') > 2]

        # Calculate statistics
        all_times = [a['total_time'] for a in self.archives if a['total_time'] > 0]
        all_points = [a['points'] for a in self.archives if a['points'] > 0]

        # Throughput (points per second during export)
        throughput = []
        for a in self.archives:
            if a['export'] > 0 and a['points'] > 0:
                throughput.append(a['points'] / a['export'])

        print("=" * 100)
        print(" " * 30 + "PCP PARSER PERFORMANCE ANALYSIS")
        print("=" * 100)
        print()

        # Overall statistics
        print("OVERALL STATISTICS:")
        print("-" * 100)
        print(f"  Total archives:           {len(self.archives)}")
        print(f"  Full-day archives:        {len(full_day)}")
        print(f"  Hourly archives:          {len(hourly)}")
        print()

        # Total processing time
        total_processing_time = sum(all_times) if all_times else 0
        print(f"  Total processing time:    {total_processing_time/60:.2f} minutes ({total_processing_time/3600:.2f} hours)")
        print()

        if all_times:
            print(f"  Average time:             {statistics.mean(all_times)/60:.2f} minutes ({statistics.mean(all_times):.2f}s)")
            print(f"  Median time:              {statistics.median(all_times)/60:.2f} minutes ({statistics.median(all_times):.2f}s)")
            print(f"  Min time:                 {min(all_times):.2f} seconds")
            print(f"  Max time:                 {max(all_times)/60:.2f} minutes ({max(all_times):.2f}s)")
            print(f"  Std deviation:            {statistics.stdev(all_times) if len(all_times) > 1 else 0:.2f} seconds")

        print()

        if all_points:
            print(f"  Average points:           {statistics.mean(all_points):,.0f}")
            print(f"  Median points:            {statistics.median(all_points):,.0f}")
            print(f"  Min points:               {min(all_points):,}")
            print(f"  Max points:               {max(all_points):,}")

        print()

        if throughput:
            print(f"  Average throughput:       {statistics.mean(throughput):.1f} points/sec")
            print(f"  Median throughput:        {statistics.median(throughput):.1f} points/sec")
            print(f"  Min throughput:           {min(throughput):.1f} points/sec")
            print(f"  Max throughput:           {max(throughput):.1f} points/sec")

        print()
        print("-" * 100)
        print()

        # Top 5 slowest
        print("TOP 5 SLOWEST ARCHIVES:")
        print("-" * 100)
        sorted_archives = sorted(self.archives, key=lambda x: x['total_time'], reverse=True)
        print(f"{'Rank':<6} {'Archive':<30} {'Total Time':<15} {'Export':<12} {'Points':<12}")
        print("-" * 100)
        for i, a in enumerate(sorted_archives[:5], 1):
            total = f"{a['total_time']/60:.2f}m"
            export = f"{a['export']/60:.2f}m"
            points = f"{a['points']:,}"
            print(f"{i:<6} {a['archive']:<30} {total:<15} {export:<12} {points:<12}")
        print()

        # Archive type comparison
        print("ARCHIVE TYPE COMPARISON:")
        print("-" * 100)

        if full_day:
            fd_times = [a['total_time'] for a in full_day]
            fd_points = [a['points'] for a in full_day]
            fd_export = [a['export'] for a in full_day]

            print(f"Full-Day Archives (YYYYMMDD.tar.xz): {len(full_day)} archives")
            print(f"  Avg time:       {statistics.mean(fd_times)/60:.2f} minutes")
            print(f"  Avg export:     {statistics.mean(fd_export)/60:.2f} minutes")
            print(f"  Avg points:     {statistics.mean(fd_points):,.0f}")
            print()

        if hourly:
            hr_times = [a['total_time'] for a in hourly]
            hr_points = [a['points'] for a in hourly]
            hr_export = [a['export'] for a in hourly]

            print(f"Hourly Archives (YYYYMMDD.HH.MM.tar.xz): {len(hourly)} archives")
            print(f"  Avg time:       {statistics.mean(hr_times)/60:.2f} minutes")
            print(f"  Avg export:     {statistics.mean(hr_export)/60:.2f} minutes")
            print(f"  Avg points:     {statistics.mean(hr_points):,.0f}")

        print()
        print("-" * 100)
        print()

        # Bottleneck analysis
        total_extraction = sum(a['extraction'] for a in self.archives)
        total_validation = sum(a['validation'] for a in self.archives)
        total_export = sum(a['export'] for a in self.archives)
        total_all = total_extraction + total_validation + total_export

        print("BOTTLENECK ANALYSIS:")
        print("-" * 100)
        print(f"  Total stage time:    {total_all/60:>8.2f} minutes ({total_all/3600:>5.2f} hours)")
        print()
        if total_all > 0:
            print(f"  Extraction:   {total_extraction/60:>8.2f} minutes ({total_extraction/total_all*100:>5.2f}%)")
            print(f"  Validation:   {total_validation/60:>8.2f} minutes ({total_validation/total_all*100:>5.2f}%)")
            print(f"  Export:       {total_export/60:>8.2f} minutes ({total_export/total_all*100:>5.2f}%) <-- PRIMARY BOTTLENECK")
        print()
        print("-" * 100)
        print()

    def generate_histograms(self):
        """Generate ASCII histograms for time distribution"""
        if not self.archives:
            return

        all_times = [a['total_time'] for a in self.archives if a['total_time'] > 0]

        print("TIME DISTRIBUTION HISTOGRAM:")
        print("-" * 100)

        # Define time buckets (in seconds)
        buckets = [
            (0, 60, '< 1 min'),
            (60, 300, '1-5 min'),
            (300, 600, '5-10 min'),
            (600, 900, '10-15 min'),
            (900, 1200, '15-20 min'),
            (1200, float('inf'), '> 20 min')
        ]

        bucket_counts = defaultdict(int)

        for time in all_times:
            for min_val, max_val, label in buckets:
                if min_val <= time < max_val:
                    bucket_counts[label] += 1
                    break

        # Print histogram
        max_count = max(bucket_counts.values()) if bucket_counts else 1

        for _, _, label in buckets:
            count = bucket_counts[label]
            percentage = (count / len(all_times)) * 100 if all_times else 0
            bar_length = int((count / max_count) * 50) if max_count > 0 else 0
            bar = '#' * bar_length

            print(f"  {label:<12} {count:>4} ({percentage:>5.1f}%)  {bar}")

        print()
        print("-" * 100)
        print()

        # Points distribution
        all_points = [a['points'] for a in self.archives if a['points'] > 0]

        if all_points:
            print("DATA POINTS DISTRIBUTION HISTOGRAM:")
            print("-" * 100)

            point_buckets = [
                (0, 100, '< 100'),
                (100, 1000, '100-1K'),
                (1000, 5000, '1K-5K'),
                (5000, 10000, '5K-10K'),
                (10000, 20000, '10K-20K'),
                (20000, float('inf'), '> 20K')
            ]

            point_counts = defaultdict(int)

            for points in all_points:
                for min_val, max_val, label in point_buckets:
                    if min_val <= points < max_val:
                        point_counts[label] += 1
                        break

            max_count = max(point_counts.values()) if point_counts else 1

            for _, _, label in point_buckets:
                count = point_counts[label]
                percentage = (count / len(all_points)) * 100 if all_points else 0
                bar_length = int((count / max_count) * 50) if max_count > 0 else 0
                bar = '#' * bar_length

                print(f"  {label:<12} {count:>4} ({percentage:>5.1f}%)  {bar}")

            print()
            print("-" * 100)
            print()

    def generate_error_report(self):
        """Generate error analysis and deduplication"""
        if not self.errors:
            print("ERROR ANALYSIS:")
            print("-" * 100)
            print("  No errors found in logs")
            print()
            print("-" * 100)
            print()
            return

        print("ERROR ANALYSIS:")
        print("-" * 100)
        print(f"  Total errors/warnings found: {len(self.errors)}")
        print()

        # Count by type
        error_counts = Counter(e['type'] for e in self.errors)

        print("Error Distribution by Type:")
        for error_type, count in error_counts.most_common():
            percentage = (count / len(self.errors)) * 100
            print(f"  {error_type:<25} {count:>6} ({percentage:>5.1f}%)")
        print()

        # Deduplicate errors by message similarity
        unique_errors = {}
        for error in self.errors:
            # Create a normalized key from the message
            normalized = re.sub(r'\d+', 'N', error['message'])  # Replace numbers with N
            normalized = re.sub(r'["\'].*?["\']', 'STR', normalized)  # Replace strings
            normalized = re.sub(r'\s+', ' ', normalized)  # Normalize whitespace

            key = (error['type'], normalized[:200])  # Use first 200 chars as key

            if key not in unique_errors:
                unique_errors[key] = {
                    'type': error['type'],
                    'example_message': error['message'][:150],
                    'count': 1,
                    'archives': [error['archive']]
                }
            else:
                unique_errors[key]['count'] += 1
                if error['archive'] not in unique_errors[key]['archives']:
                    unique_errors[key]['archives'].append(error['archive'])

        print(f"Unique Error Types (deduplicated): {len(unique_errors)}")
        print()
        print("-" * 100)
        print()

        # Display unique errors table
        print("UNIQUE ERRORS TABLE:")
        print("=" * 100)
        print(f"{'Type':<20} {'Count':<8} {'Archives':<12} {'Example Message'}")
        print("=" * 100)

        # Sort by count descending
        sorted_errors = sorted(unique_errors.values(), key=lambda x: x['count'], reverse=True)

        for i, error in enumerate(sorted_errors[:50], 1):  # Show top 50
            error_type = error['type']
            count = error['count']
            num_archives = len(error['archives'])
            example = error['example_message'][:60] + '...' if len(error['example_message']) > 60 else error['example_message']

            print(f"{error_type:<20} {count:<8} {num_archives:<12} {example}")

        if len(sorted_errors) > 50:
            print(f"\n... and {len(sorted_errors) - 50} more unique error types")

        print()
        print("-" * 100)
        print()

        return unique_errors

    def generate_visual_histograms(self):
        """Generate visual histograms using matplotlib"""
        if not HAS_MATPLOTLIB:
            return

        if not self.archives:
            return

        print("Generating visual histograms...")

        # Prepare data
        all_times = [a['total_time']/60 for a in self.archives if a['total_time'] > 0]  # Convert to minutes
        all_points = [a['points'] for a in self.archives if a['points'] > 0]
        extraction_times = [a['extraction'] for a in self.archives if a['extraction'] > 0]
        validation_times = [a['validation'] for a in self.archives if a['validation'] > 0]
        export_times = [a['export']/60 for a in self.archives if a['export'] > 0]  # Convert to minutes

        # Create figure with subplots
        fig, axes = plt.subplots(2, 3, figsize=(18, 12))
        fig.suptitle('PCP Parser Performance Analysis', fontsize=16, fontweight='bold')

        # 1. Processing Time Distribution
        axes[0, 0].hist(all_times, bins=30, color='steelblue', edgecolor='black', alpha=0.7)
        axes[0, 0].set_xlabel('Processing Time (minutes)')
        axes[0, 0].set_ylabel('Frequency')
        axes[0, 0].set_title('Processing Time Distribution')
        axes[0, 0].grid(True, alpha=0.3)

        # 2. Data Points Distribution
        axes[0, 1].hist(all_points, bins=30, color='green', edgecolor='black', alpha=0.7)
        axes[0, 1].set_xlabel('Data Points')
        axes[0, 1].set_ylabel('Frequency')
        axes[0, 1].set_title('Data Points Distribution')
        axes[0, 1].grid(True, alpha=0.3)

        # 3. Processing Stage Comparison
        stage_times = [
            sum(extraction_times),
            sum(validation_times),
            sum(export_times)
        ]
        stage_labels = ['Extraction', 'Validation', 'Export']
        colors = ['#ff9999', '#66b3ff', '#99ff99']
        axes[0, 2].bar(stage_labels, stage_times, color=colors, edgecolor='black')
        axes[0, 2].set_ylabel('Total Time (seconds)')
        axes[0, 2].set_title('Processing Stage Comparison')
        axes[0, 2].grid(True, alpha=0.3, axis='y')

        # 4. Export Time Distribution
        axes[1, 0].hist(export_times, bins=25, color='coral', edgecolor='black', alpha=0.7)
        axes[1, 0].set_xlabel('Export Time (minutes)')
        axes[1, 0].set_ylabel('Frequency')
        axes[1, 0].set_title('Export Time Distribution (Bottleneck)')
        axes[1, 0].grid(True, alpha=0.3)

        # 5. Throughput Distribution
        throughput = [a['points']/a['export'] for a in self.archives if a['export'] > 0 and a['points'] > 0]
        axes[1, 1].hist(throughput, bins=30, color='purple', edgecolor='black', alpha=0.7)
        axes[1, 1].set_xlabel('Throughput (points/sec)')
        axes[1, 1].set_ylabel('Frequency')
        axes[1, 1].set_title('Throughput Distribution')
        axes[1, 1].grid(True, alpha=0.3)

        # 6. Processing Time vs Data Points (Scatter)
        points_for_scatter = [a['points'] for a in self.archives if a['total_time'] > 0 and a['points'] > 0]
        times_for_scatter = [a['total_time']/60 for a in self.archives if a['total_time'] > 0 and a['points'] > 0]
        axes[1, 2].scatter(points_for_scatter, times_for_scatter, alpha=0.6, c='darkblue', edgecolor='black')
        axes[1, 2].set_xlabel('Data Points')
        axes[1, 2].set_ylabel('Processing Time (minutes)')
        axes[1, 2].set_title('Processing Time vs Data Points')
        axes[1, 2].grid(True, alpha=0.3)

        plt.tight_layout()

        # Save figure
        output_file = 'pcp_analysis_histograms.png'
        plt.savefig(output_file, dpi=150, bbox_inches='tight')
        print(f"[OK] Saved visual histograms to: {output_file}")
        print()
        plt.close()

    def export_csv(self, output_file="pcp_analysis.csv"):
        """Export detailed data to CSV for further analysis"""
        output_path = Path(output_file)

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'archive', 'total_time', 'extraction', 'validation', 'export',
                'points', 'lines', 'throughput', 'archive_type'
            ])
            writer.writeheader()

            for a in self.archives:
                throughput = a['points'] / a['export'] if a['export'] > 0 else 0
                archive_type = 'full_day' if a['archive'].count('.') == 2 else 'hourly'

                writer.writerow({
                    'archive': a['archive'],
                    'total_time': a['total_time'],
                    'extraction': a['extraction'],
                    'validation': a['validation'],
                    'export': a['export'],
                    'points': a['points'],
                    'lines': a['lines'],
                    'throughput': throughput,
                    'archive_type': archive_type
                })

        print(f"[OK] Exported detailed data to: {output_path}")
        print()

    def export_errors_csv(self, unique_errors, output_file="pcp_errors.csv"):
        """Export unique errors to CSV"""
        if not unique_errors:
            return

        output_path = Path(output_file)

        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'error_type', 'count', 'num_archives', 'example_message', 'affected_archives'
            ])
            writer.writeheader()

            sorted_errors = sorted(unique_errors.values(), key=lambda x: x['count'], reverse=True)

            for error in sorted_errors:
                writer.writerow({
                    'error_type': error['type'],
                    'count': error['count'],
                    'num_archives': len(error['archives']),
                    'example_message': error['example_message'],
                    'affected_archives': ', '.join(error['archives'][:5])  # First 5 archives
                })

        print(f"[OK] Exported error analysis to: {output_path}")
        print()


def compare_logs(log_files, labels=None):
    """Compare multiple log files and show performance differences"""
    if labels is None:
        labels = [f"Log {i+1}" for i in range(len(log_files))]

    analyzers = []

    print("=" * 100)
    print(" " * 30 + "MULTI-LOG COMPARISON ANALYSIS")
    print("=" * 100)
    print()

    # Parse all log files
    for log_file, label in zip(log_files, labels):
        print(f"Parsing: {label} - {log_file}")
        analyzer = PCPLogAnalyzer(log_file)
        analyzer.parse_log()
        analyzers.append((label, analyzer))

    print()
    print("=" * 100)
    print(" " * 35 + "COMPARISON RESULTS")
    print("=" * 100)
    print()

    # Compare key metrics
    print("PERFORMANCE COMPARISON:")
    print("-" * 100)
    print(f"{'Metric':<40} " + " ".join([f"{label:>15}" for label in labels]))
    print("-" * 100)

    # Total archives
    archive_counts = [len(a.archives) for _, a in analyzers]
    print(f"{'Total archives':<40} " + " ".join([f"{count:>15,}" for count in archive_counts]))

    # Total processing time (sum of all archives)
    total_times = []
    for _, analyzer in analyzers:
        times = [a['total_time'] for a in analyzer.archives if a['total_time'] > 0]
        total_times.append(sum(times) if times else 0)

    # Display total time in hours if > 60 minutes, otherwise minutes
    total_time_display = []
    for t in total_times:
        if t > 3600:  # More than 60 minutes
            total_time_display.append(f"{t/3600:>13.2f}h")
        else:
            total_time_display.append(f"{t/60:>13.2f}m")
    print(f"{'Total processing time':<40} " + " ".join(total_time_display))

    # Average processing time per archive
    avg_times = []
    for _, analyzer in analyzers:
        times = [a['total_time'] for a in analyzer.archives if a['total_time'] > 0]
        avg_times.append(statistics.mean(times) if times else 0)
    print(f"{'Avg processing time (min)':<40} " + " ".join([f"{t/60:>15.2f}" for t in avg_times]))

    # Average throughput
    avg_throughputs = []
    for _, analyzer in analyzers:
        throughput = [a['points']/a['export'] for a in analyzer.archives if a['export'] > 0 and a['points'] > 0]
        avg_throughputs.append(statistics.mean(throughput) if throughput else 0)
    print(f"{'Avg throughput (pts/sec)':<40} " + " ".join([f"{t:>15.1f}" for t in avg_throughputs]))

    # Average points
    avg_points = []
    for _, analyzer in analyzers:
        points = [a['points'] for a in analyzer.archives if a['points'] > 0]
        avg_points.append(statistics.mean(points) if points else 0)
    print(f"{'Avg data points':<40} " + " ".join([f"{p:>15,.0f}" for p in avg_points]))

    # Total errors
    error_counts = [len(a.errors) for _, a in analyzers]
    print(f"{'Total errors/warnings':<40} " + " ".join([f"{e:>15,}" for e in error_counts]))

    print()
    print("-" * 100)
    print()

    # Show improvement percentages (comparing to first log)
    if len(analyzers) > 1:
        print("IMPROVEMENT ANALYSIS (vs first log):")
        print("-" * 100)

        baseline_total_time = total_times[0]
        baseline_avg_time = avg_times[0]
        baseline_throughput = avg_throughputs[0]
        baseline_errors = error_counts[0]

        for i, (label, _) in enumerate(analyzers[1:], 1):
            print(f"\n{label} vs {labels[0]}:")

            # Total processing time improvement
            if baseline_total_time > 0:
                total_time_improvement = ((baseline_total_time - total_times[i]) / baseline_total_time) * 100
                print(f"  Total proc time: {total_time_improvement:+.1f}% {'(faster)' if total_time_improvement > 0 else '(slower)'}")

            # Average processing time improvement
            if baseline_avg_time > 0:
                avg_time_improvement = ((baseline_avg_time - avg_times[i]) / baseline_avg_time) * 100
                print(f"  Avg proc time:   {avg_time_improvement:+.1f}% {'(faster)' if avg_time_improvement > 0 else '(slower)'}")

            # Throughput improvement
            if baseline_throughput > 0:
                throughput_improvement = ((avg_throughputs[i] - baseline_throughput) / baseline_throughput) * 100
                print(f"  Throughput:      {throughput_improvement:+.1f}% {'(faster)' if throughput_improvement > 0 else '(slower)'}")

            # Error reduction
            if baseline_errors > 0:
                error_improvement = ((baseline_errors - error_counts[i]) / baseline_errors) * 100
                print(f"  Error reduction: {error_improvement:+.1f}% {'(fewer errors)' if error_improvement > 0 else '(more errors)'}")

        print()
        print("-" * 100)
        print()

    # Export comparison CSV
    comparison_file = "pcp_comparison.csv"
    with open(comparison_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Metric'] + labels)
        writer.writerow(['Total Archives'] + archive_counts)
        writer.writerow(['Total Processing Time (min)'] + [t/60 for t in total_times])
        writer.writerow(['Avg Processing Time (min)'] + [t/60 for t in avg_times])
        writer.writerow(['Avg Throughput (pts/sec)'] + avg_throughputs)
        writer.writerow(['Avg Data Points'] + avg_points)
        writer.writerow(['Total Errors'] + error_counts)

    print(f"[OK] Exported comparison to: {comparison_file}")
    print()


def main():
    """Main execution with argument parsing"""
    parser = argparse.ArgumentParser(
        description='Analyze PCP parser log files and compare performance',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Analyze single log (default)
  python analyze_pcp_logs.py

  # Analyze specific log file
  python analyze_pcp_logs.py -f src/logs/pcp_parser_python/2pcp_parser.log

  # Compare multiple logs (before/after optimization)
  python analyze_pcp_logs.py --compare \
    src/logs/pcp_parser_python/1pcp_parser.log \
    src/logs/pcp_parser_python/2pcp_parser.log \
    --labels "Before Optimization" "After Optimization"

  # Compare three logs
  python analyze_pcp_logs.py --compare \
    src/logs/pcp_parser_python/1pcp_parser.log \
    src/logs/pcp_parser_python/2pcp_parser.log \
    src/logs/pcp_parser_python/3pcp_parser.log \
    --labels "Baseline" "Optimized v1" "Optimized v2"
        '''
    )

    parser.add_argument(
        '-f', '--file',
        type=str,
        default=None,
        help=f'Single log file to analyze (default: {DEFAULT_LOG_FILE})'
    )

    parser.add_argument(
        '--compare',
        nargs='+',
        metavar='LOG_FILE',
        help='Compare multiple log files (space-separated paths)'
    )

    parser.add_argument(
        '--labels',
        nargs='+',
        metavar='LABEL',
        help='Labels for comparison logs (must match number of --compare files)'
    )

    args = parser.parse_args()

    # Comparison mode
    if args.compare:
        log_files = [Path(f) for f in args.compare]

        # Validate all files exist
        for log_file in log_files:
            if not log_file.exists():
                print(f"Error: Log file not found: {log_file}")
                sys.exit(1)

        # Validate labels if provided
        if args.labels and len(args.labels) != len(log_files):
            print(f"Error: Number of labels ({len(args.labels)}) must match number of files ({len(log_files)})")
            sys.exit(1)

        compare_logs(log_files, args.labels)
        return

    # Single file mode
    if args.file:
        log_file = Path(args.file)
    else:
        log_file = Path(__file__).parent / DEFAULT_LOG_FILE

    if not log_file.exists():
        print(f"Error: Log file not found: {log_file}")
        sys.exit(1)

    analyzer = PCPLogAnalyzer(log_file)

    # Parse log
    analyzer.parse_log()

    # Generate statistics
    analyzer.generate_statistics()

    # Generate ASCII histograms
    analyzer.generate_histograms()

    # Generate error report
    unique_errors = analyzer.generate_error_report()

    # Generate visual histograms (if matplotlib available)
    analyzer.generate_visual_histograms()

    # Export CSVs
    analyzer.export_csv()
    if unique_errors:
        analyzer.export_errors_csv(unique_errors)

    print("=" * 100)
    print("Analysis complete!")
    print("=" * 100)


if __name__ == "__main__":
    main()
