#!/usr/bin/env python3
"""
PCP Web Control Panel
Web interface for managing PCP archive files
"""
from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
import logging

app = Flask(__name__)

# Configuration
INPUT_DIR = Path("/src/input/raw")
PROCESSED_DIR = Path("/src/archive/processed")
FAILED_DIR = Path("/src/archive/failed")
LOG_DIR = Path("/src/logs")
UPLOAD_FOLDER = INPUT_DIR
ENV_FILE = Path("/src/.env")

# Allowed extensions
ALLOWED_EXTENSIONS = {'tar.xz', 'tar', 'xz'}

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Ensure directories exist
for directory in [INPUT_DIR, PROCESSED_DIR, FAILED_DIR, LOG_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

def allowed_file(filename):
    """Check if file has allowed extension"""
    return '.' in filename and any(
        filename.endswith(f'.{ext}') for ext in ALLOWED_EXTENSIONS
    )

def get_directory_info(directory):
    """Get information about files in a directory"""
    if not directory.exists():
        return []

    files = []
    for file_path in directory.iterdir():
        if file_path.is_file():
            stat = file_path.stat()
            files.append({
                'name': file_path.name,
                'size': stat.st_size,
                'size_mb': round(stat.st_size / (1024 * 1024), 2),
                'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            })
    return sorted(files, key=lambda x: x['modified'], reverse=True)

def get_log_files(log_dir):
    """Get log files from subdirectories"""
    logs = []
    if not log_dir.exists():
        return logs

    for subdir in log_dir.iterdir():
        if subdir.is_dir():
            for log_file in subdir.glob('*.log*'):
                stat = log_file.stat()
                logs.append({
                    'name': f"{subdir.name}/{log_file.name}",
                    'path': str(log_file.relative_to(log_dir)),
                    'size': stat.st_size,
                    'size_kb': round(stat.st_size / 1024, 2),
                    'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                })
    return sorted(logs, key=lambda x: x['modified'], reverse=True)

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/api/files/input')
def get_input_files():
    """Get list of files in input directory"""
    return jsonify(get_directory_info(INPUT_DIR))

@app.route('/api/files/processed')
def get_processed_files():
    """Get list of files in processed directory"""
    return jsonify(get_directory_info(PROCESSED_DIR))

@app.route('/api/files/failed')
def get_failed_files():
    """Get list of files in failed directory"""
    return jsonify(get_directory_info(FAILED_DIR))

@app.route('/api/logs')
def get_logs():
    """Get list of log files"""
    return jsonify(get_log_files(LOG_DIR))

@app.route('/api/csv')
def get_csv_files():
    """Get list of CSV files in logs directory"""
    csvs = []
    if not LOG_DIR.exists():
        return jsonify(csvs)

    for subdir in LOG_DIR.iterdir():
        if subdir.is_dir():
            for csv_file in subdir.glob('*.csv'):
                stat = csv_file.stat()
                csvs.append({
                    'name': f"{subdir.name}/{csv_file.name}",
                    'path': str(csv_file.relative_to(LOG_DIR)),
                    'size': stat.st_size,
                    'size_mb': round(stat.st_size / (1024 * 1024), 2),
                    'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                })
    return jsonify(sorted(csvs, key=lambda x: x['modified'], reverse=True))

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Upload file to input directory"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': f'Invalid file type. Allowed: {", ".join(ALLOWED_EXTENSIONS)}'}), 400

    try:
        filepath = INPUT_DIR / file.filename
        file.save(str(filepath))
        logger.info(f"Uploaded file: {file.filename}")
        return jsonify({
            'success': True,
            'message': f'File {file.filename} uploaded successfully',
            'filename': file.filename
        })
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete/input/<filename>', methods=['DELETE'])
def delete_input_file(filename):
    """Delete file from input directory"""
    try:
        filepath = INPUT_DIR / filename
        if filepath.exists():
            filepath.unlink()
            logger.info(f"Deleted input file: {filename}")
            return jsonify({'success': True, 'message': f'Deleted {filename}'})
        else:
            return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        logger.error(f"Delete error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete/processed/<filename>', methods=['DELETE'])
def delete_processed_file(filename):
    """Delete file from processed directory"""
    try:
        filepath = PROCESSED_DIR / filename
        if filepath.exists():
            filepath.unlink()
            logger.info(f"Deleted processed file: {filename}")
            return jsonify({'success': True, 'message': f'Deleted {filename}'})
        else:
            return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        logger.error(f"Delete error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete/failed/<filename>', methods=['DELETE'])
def delete_failed_file(filename):
    """Delete file from failed directory"""
    try:
        filepath = FAILED_DIR / filename
        if filepath.exists():
            filepath.unlink()
            logger.info(f"Deleted failed file: {filename}")
            return jsonify({'success': True, 'message': f'Deleted {filename}'})
        else:
            return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        logger.error(f"Delete error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete/logs/<path:filename>', methods=['DELETE'])
def delete_log_file(filename):
    """Delete log file"""
    try:
        filepath = LOG_DIR / filename
        if filepath.exists() and filepath.is_file():
            filepath.unlink()
            logger.info(f"Deleted log file: {filename}")
            return jsonify({'success': True, 'message': f'Deleted {filename}'})
        else:
            return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        logger.error(f"Delete error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/delete/csv/<path:filename>', methods=['DELETE'])
def delete_csv_file(filename):
    """Delete CSV file"""
    try:
        filepath = LOG_DIR / filename
        if filepath.exists() and filepath.is_file() and filepath.suffix == '.csv':
            filepath.unlink()
            logger.info(f"Deleted CSV file: {filename}")
            return jsonify({'success': True, 'message': f'Deleted {filename}'})
        else:
            return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        logger.error(f"Delete error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/clear/input', methods=['POST'])
def clear_input():
    """Clear all files from input directory"""
    try:
        count = 0
        for file_path in INPUT_DIR.iterdir():
            if file_path.is_file():
                file_path.unlink()
                count += 1
        logger.info(f"Cleared {count} input files")
        return jsonify({'success': True, 'message': f'Deleted {count} files'})
    except Exception as e:
        logger.error(f"Clear error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/clear/processed', methods=['POST'])
def clear_processed():
    """Clear all files from processed directory"""
    try:
        count = 0
        for file_path in PROCESSED_DIR.iterdir():
            if file_path.is_file():
                file_path.unlink()
                count += 1
        logger.info(f"Cleared {count} processed files")
        return jsonify({'success': True, 'message': f'Deleted {count} files'})
    except Exception as e:
        logger.error(f"Clear error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/clear/logs', methods=['POST'])
def clear_logs():
    """Clear all log files"""
    try:
        count = 0
        for subdir in LOG_DIR.iterdir():
            if subdir.is_dir():
                for log_file in subdir.glob('*.log*'):
                    log_file.unlink()
                    count += 1
        logger.info(f"Cleared {count} log files")
        return jsonify({'success': True, 'message': f'Deleted {count} log files'})
    except Exception as e:
        logger.error(f"Clear error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/clear/csv', methods=['POST'])
def clear_csv_files():
    """Clear all CSV files except metrics_labels.csv"""
    try:
        count = 0
        for subdir in LOG_DIR.iterdir():
            if subdir.is_dir():
                for csv_file in subdir.glob('*.csv'):
                    # Skip metrics_labels.csv
                    if csv_file.name == 'metrics_labels.csv':
                        logger.info(f"Skipping metrics_labels.csv (preserved)")
                        continue
                    csv_file.unlink()
                    count += 1
        logger.info(f"Cleared {count} CSV files (metrics_labels.csv preserved)")
        return jsonify({'success': True, 'message': f'Deleted {count} CSV files (metrics_labels.csv preserved)'})
    except Exception as e:
        logger.error(f"Clear error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/stats')
def get_stats():
    """Get statistics"""
    return jsonify({
        'input_count': len(list(INPUT_DIR.glob('*'))),
        'processed_count': len(list(PROCESSED_DIR.glob('*'))),
        'failed_count': len(list(FAILED_DIR.glob('*'))),
        'log_count': sum(1 for _ in LOG_DIR.rglob('*.log*')),
        'csv_count': sum(1 for _ in LOG_DIR.rglob('*.csv'))
    })

@app.route('/api/config', methods=['GET'])
def get_config():
    """Get current configuration"""
    config = {
        'product_type': os.getenv('PRODUCT_TYPE', 'SERVER1'),
        'serial_number': os.getenv('SERIAL_NUMBER', '1234')
    }

    # Try to read from .env file if it exists
    if ENV_FILE.exists():
        try:
            with open(ENV_FILE, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('PRODUCT_TYPE='):
                        config['product_type'] = line.split('=', 1)[1]
                    elif line.startswith('SERIAL_NUMBER='):
                        config['serial_number'] = line.split('=', 1)[1]
        except Exception as e:
            logger.error(f"Error reading config: {str(e)}")

    return jsonify(config)

@app.route('/api/config', methods=['POST'])
def update_config():
    """Update configuration"""
    try:
        data = request.json
        product_type = data.get('product_type', 'ANY').strip()
        serial_number = data.get('serial_number', 'ANY').strip()

        # Write to .env file
        with open(ENV_FILE, 'w') as f:
            f.write(f"PRODUCT_TYPE={product_type}\n")
            f.write(f"SERIAL_NUMBER={serial_number}\n")

        logger.info(f"Updated config: PRODUCT_TYPE={product_type}, SERIAL_NUMBER={serial_number}")

        # Automatically restart pcp_parser container
        restart_success = False
        restart_message = ""
        try:
            # Execute docker-compose restart from /src directory
            result = subprocess.run(
                ['docker-compose', 'restart', 'pcp_parser'],
                cwd='/src',
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                restart_success = True
                restart_message = "Configuration updated and pcp_parser container restarted successfully."
                logger.info("Successfully restarted pcp_parser container")
            else:
                restart_message = f"Configuration updated but container restart failed: {result.stderr}"
                logger.warning(f"Container restart failed: {result.stderr}")
        except subprocess.TimeoutExpired:
            restart_message = "Configuration updated but container restart timed out."
            logger.error("Container restart timed out")
        except Exception as restart_error:
            restart_message = f"Configuration updated but container restart failed: {str(restart_error)}"
            logger.error(f"Container restart error: {str(restart_error)}")

        return jsonify({
            'success': True,
            'message': restart_message,
            'restart_success': restart_success,
            'config': {
                'product_type': product_type,
                'serial_number': serial_number
            }
        })
    except Exception as e:
        logger.error(f"Config update error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/process', methods=['POST'])
def trigger_process():
    """Trigger PCP archive processing"""
    try:
        trigger_file = Path("/src/.process_trigger")

        # Check if processing is already running
        if trigger_file.exists():
            return jsonify({
                'success': False,
                'message': 'Processing is already in progress. Please wait.'
            }), 409

        # Check if there are files to process
        input_count = len(list(INPUT_DIR.glob('*.tar.xz')))
        if input_count == 0:
            return jsonify({
                'success': False,
                'message': 'No .tar.xz files found in input directory'
            }), 400

        # Create trigger file
        trigger_file.touch()
        logger.info(f"Processing triggered for {input_count} file(s)")

        return jsonify({
            'success': True,
            'message': f'Processing started for {input_count} file(s). Check logs for progress.',
            'file_count': input_count
        })
    except Exception as e:
        logger.error(f"Process trigger error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/processing-status', methods=['GET'])
def get_processing_status():
    """Get current processing status"""
    try:
        trigger_file = Path("/src/.process_trigger")
        is_processing = trigger_file.exists()

        # Get latest log entries
        log_file = LOG_DIR / "pcp_parser" / "pcp_parser.log"
        recent_logs = []

        if log_file.exists():
            try:
                with open(log_file, 'r') as f:
                    lines = f.readlines()
                    recent_logs = [line.strip() for line in lines[-10:] if line.strip()]
            except Exception as e:
                logger.debug(f"Could not read log: {e}")

        return jsonify({
            'is_processing': is_processing,
            'recent_logs': recent_logs
        })
    except Exception as e:
        logger.error(f"Status check error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/log-content/<path:filename>', methods=['GET'])
def get_log_content(filename):
    """Get full content of a log file"""
    try:
        filepath = LOG_DIR / filename
        if not filepath.exists() or not filepath.is_file():
            return jsonify({'error': 'File not found'}), 404

        # Read the entire file
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        return jsonify({
            'success': True,
            'filename': filename,
            'content': content,
            'size': filepath.stat().st_size
        })
    except Exception as e:
        logger.error(f"Error reading log file: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/csv-content/<path:filename>', methods=['GET'])
def get_csv_content(filename):
    """Get full content of a CSV file"""
    try:
        filepath = LOG_DIR / filename
        if not filepath.exists() or not filepath.is_file():
            return jsonify({'error': 'File not found'}), 404

        # Read the entire CSV file
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        return jsonify({
            'success': True,
            'filename': filename,
            'content': content,
            'size': filepath.stat().st_size
        })
    except Exception as e:
        logger.error(f"Error reading CSV file: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/download/log/<path:filename>', methods=['GET'])
def download_log(filename):
    """Download a log file"""
    try:
        filepath = LOG_DIR / filename
        if not filepath.exists() or not filepath.is_file():
            return jsonify({'error': 'File not found'}), 404

        directory = str(filepath.parent)
        return send_from_directory(directory, filepath.name, as_attachment=True)
    except Exception as e:
        logger.error(f"Error downloading log file: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/download/csv/<path:filename>', methods=['GET'])
def download_csv(filename):
    """Download a CSV file"""
    try:
        filepath = LOG_DIR / filename
        if not filepath.exists() or not filepath.is_file():
            return jsonify({'error': 'File not found'}), 404

        directory = str(filepath.parent)
        return send_from_directory(directory, filepath.name, as_attachment=True)
    except Exception as e:
        logger.error(f"Error downloading CSV file: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
