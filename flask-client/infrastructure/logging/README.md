# Logging Infrastructure

This folder contains the logging infrastructure for the Flask application.

## Overview

The logging provider implements a thread-safe, singleton-based logging system that writes all application logs to timestamped text files with full context tracking.

## Features

- **Singleton Pattern**: Only one logging instance exists throughout the application lifetime
- **Threaded Logging**: Logs are written in a separate thread to avoid blocking the main application
- **Timestamped Files**: Each application start creates a new log file with format `logs_YYYYMMDD_HHMMSS.txt`
- **Context Tracking**: Automatically captures thread name, module name, and function name
- **Log Levels**: Supports `info()`, `error()`, `warning()`, `debug()`, and general `log()` methods
- **Automatic Cleanup**: Logger stops gracefully when the application exits

## Log Format

Each log entry includes comprehensive context information:

```
[YYYY-MM-DD HH:MM:SS.mmm] [ThreadName] [module.function] MESSAGE
```

Example:
```
[2026-01-31 16:30:45.123] [MainThread] [camera_controller.process_video_stream_background] INFO: [Thread webcam_0] Starting stream processing
[2026-01-31 16:30:45.456] [Thread-1] [iris_input_processor.generate_iris_input_data] INFO: [IRIS] Creating new CSV file
[2026-01-31 16:30:46.789] [WorkerThread-2] [sftp_processor.transferData] INFO: Successfully uploaded data.csv to /remote/path/data.csv
```

## Usage

### Initialization (in app.py)

```python
from infrastructure.logging.logging_provider import get_logger

# Get logger instance
logger = get_logger()

# Start the logging thread
logger.start()
```

### Using in Other Files

```python
from infrastructure.logging.logging_provider import get_logger

logger = get_logger()

# Log messages - context is captured automatically
logger.info("Application started")
logger.error("An error occurred")
logger.warning("This is a warning")
logger.debug("Debug information")
```

**No need to manually specify thread or module names** - the logger automatically captures:
- **Thread Name**: The name of the thread making the log call
- **Module Name**: The Python file (controller, processor, etc.)
- **Function Name**: The function that called the logger

## Log File Location

Log files are stored in: `flask-client/logs/`

Each log entry includes:
1. **Timestamp**: Millisecond precision
2. **Thread Name**: Shows which thread generated the log (e.g., MainThread, Thread-1, WorkerThread-2)
3. **Module.Function**: Shows the exact location in code (e.g., camera_controller.process_video_stream)
4. **Message**: The actual log message with any level prefix (INFO, ERROR, WARNING, DEBUG)

## Implementation Details

- Uses Python's `queue.Queue` for thread-safe message passing
- Uses `inspect` module to automatically capture caller context
- Implements a worker thread that continuously processes log messages
- Automatically flushes after each write to ensure data persistence
- Falls back to console output if logging hasn't been started yet
- Thread names can be set explicitly for better tracking:
  ```python
  import threading
  threading.current_thread().name = "VideoProcessor-1"
  ```
