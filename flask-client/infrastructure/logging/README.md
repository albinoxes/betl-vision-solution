# Logging Infrastructure

This folder contains the logging infrastructure for the Flask application.

## Overview

The logging provider implements a thread-safe, singleton-based logging system that writes all application logs to timestamped text files.

## Features

- **Singleton Pattern**: Only one logging instance exists throughout the application lifetime
- **Threaded Logging**: Logs are written in a separate thread to avoid blocking the main application
- **Timestamped Files**: Each application start creates a new log file with format `logs_YYYYMMDD_HHMMSS.txt`
- **Log Levels**: Supports `info()`, `error()`, `warning()`, `debug()`, and general `log()` methods
- **Automatic Cleanup**: Logger stops gracefully when the application exits

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

# Log messages
logger.info("Application started")
logger.error("An error occurred")
logger.warning("This is a warning")
logger.debug("Debug information")
```

## Log File Location

Log files are stored in: `flask-client/logs/`

Each log entry includes a timestamp in the format: `[YYYY-MM-DD HH:MM:SS.mmm] MESSAGE`

## Implementation Details

- Uses Python's `queue.Queue` for thread-safe message passing
- Implements a worker thread that continuously processes log messages
- Automatically flushes after each write to ensure data persistence
- Falls back to console output if logging hasn't been started yet
