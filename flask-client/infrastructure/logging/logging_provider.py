##
# @file logging_provider.py
# @brief Logging provider module for Belt Vision application
# @details This module provides efficient logging using Python's standard logging library
#          with async queue-based handlers, rotating files, and custom formatting.
# @author Belt Vision Team
# @date 2026-02-06

import logging
import threading
import queue
import atexit
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler, QueueHandler, QueueListener

# Module-level variables for the logging system
_logger = None
_queue_listener = None
_file_handler = None
_log_queue = None
_listener_started = False
_init_lock = threading.Lock()
_log_file_path = None


def _initialize_logging():
    """
    Initialize the global logging system.
    This function is called once and sets up the entire logging infrastructure.
    Thread-safe initialization using double-checked locking.
    """
    global _logger, _queue_listener, _file_handler, _log_queue, _listener_started, _log_file_path
    
    if _logger is not None:
        return _logger
    
    with _init_lock:
        # Double-check pattern
        if _logger is not None:
            return _logger
        
        # Setup logs directory
        logs_dir = Path(__file__).parent.parent.parent / 'logs'
        logs_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        _log_file_path = logs_dir / f'logs_{timestamp}.txt'
        
        # Configure root logger for the application
        _logger = logging.getLogger('BeltVisionApp')
        _logger.setLevel(logging.DEBUG)
        _logger.propagate = False  # Don't propagate to root logger
        
        # Clear any existing handlers
        _logger.handlers.clear()
        
        # Create rotating file handler
        _file_handler = RotatingFileHandler(
            _log_file_path,
            maxBytes=10*1024*1024,  # 10 MB
            backupCount=5,
            encoding='utf-8'
        )
        _file_handler.setLevel(logging.DEBUG)
        _file_handler.setFormatter(CustomFormatter())
        
        # Create unbounded queue for async logging (no blocking)
        # Using unbounded queue to prevent application blocking
        _log_queue = queue.Queue()
        
        # Create QueueHandler - this is what the application uses (non-blocking)
        queue_handler = QueueHandler(_log_queue)
        _logger.addHandler(queue_handler)
        
        # Create QueueListener - processes logs in background thread
        _queue_listener = QueueListener(
            _log_queue,
            _file_handler,
            respect_handler_level=True
        )
        
        # Start the queue listener immediately
        _queue_listener.start()
        _listener_started = True
        
        # Register cleanup on exit
        atexit.register(_cleanup_logging)
        
        _logger.info(f"Logging system initialized - Log file: {_log_file_path}")
        
        return _logger


def _cleanup_logging():
    """
    Cleanup the logging system.
    Stops the queue listener, flushes logs, and closes file handlers.
    """
    global _queue_listener, _file_handler, _log_queue, _listener_started, _logger
    
    if _listener_started and _queue_listener:
        try:
            # Stop the queue listener (this waits for remaining logs to be written)
            _queue_listener.stop()
            _listener_started = False
            
            # Flush and close file handler
            if _file_handler:
                _file_handler.flush()
                _file_handler.close()
            
            # Clear the queue to free memory
            if _log_queue:
                while not _log_queue.empty():
                    try:
                        _log_queue.get_nowait()
                    except queue.Empty:
                        break
                        
        except Exception as e:
            print(f"Error during logging cleanup: {e}")


##
# @class LoggingWrapper
# @brief Wrapper class providing a convenient interface to the logging system
# @details Provides methods like info(), error(), warning(), debug() that delegate
#          to the underlying Python logger. This class is lightweight and doesn't
#          maintain state - all state is in the module-level logger.
class LoggingWrapper:
    """
    Lightweight wrapper around the standard Python logger.
    This class is stateless and just provides a convenient API.
    """
    
    def __init__(self):
        """Initialize the wrapper - ensures logging system is initialized."""
        _initialize_logging()
    
    def log(self, message):
        """Log an info message."""
        _logger.info(message)
    
    def info(self, message):
        """Log an info message."""
        _logger.info(message)
    
    def error(self, message, exc_info=False):
        """Log an error message with optional exception info."""
        _logger.error(message, exc_info=exc_info)
    
    def warning(self, message):
        """Log a warning message."""
        _logger.warning(message)
    
    def debug(self, message):
        """Log a debug message."""
        _logger.debug(message)
    
    def start(self):
        """Start logging - for backward compatibility (no-op as listener auto-starts)."""
        pass
    
    def stop(self):
        """Stop the logging service."""
        _logger.info("Logging service stopping...")
        _cleanup_logging()
    
    def get_queue_size(self):
        """Get current queue size for monitoring."""
        return _log_queue.qsize() if _log_queue else 0
    
    def get_stats(self):
        """Get logging statistics."""
        return {
            'queue_size': _log_queue.qsize() if _log_queue else 0,
            'queue_maxsize': 0,  # Unbounded
            'log_file': str(_log_file_path) if _log_file_path else None,
            'listener_running': _listener_started
        }


# Legacy class name for backward compatibility
LoggingProvider = LoggingWrapper

##
# @class CustomFormatter
# @brief Custom log formatter for structured log output
# @details Extends logging.Formatter to provide a custom format:
#          [YYYY-MM-DD HH:MM:SS] [LEVEL] [ThreadName] [module.function] message
#          Includes exception information when available.
class CustomFormatter(logging.Formatter):
    ##
    # @brief Format a log record
    # @details Formats the log record with timestamp, level, thread name, module/function,
    #          and message. Appends exception information if present in the record.
    # @param record The LogRecord instance to format
    # @return Formatted log string
    def format(self, record):
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')
        level = record.levelname
        thread_name = record.threadName
        module_name = Path(record.pathname).stem
        function_name = record.funcName
        log_entry = f"[{timestamp}] [{level}] [{thread_name}] [{module_name}.{function_name}] {record.getMessage()}"
        
        if record.exc_info:
            log_entry += '\n' + self.formatException(record.exc_info)
        
        return log_entry


##
# @brief Get the LoggingWrapper instance
# @details Convenience function to obtain a logging wrapper instance.
#          The wrapper is lightweight and stateless - all state is in the module-level logger.
# @return A LoggingWrapper instance
def get_logger():
    """
    Get a logger instance for the Belt Vision application.
    
    This function returns a lightweight wrapper around the centralized logging system.
    The wrapper is stateless and can be created multiple times without overhead.
    All log messages go through the same queue-based async logging infrastructure.
    
    Returns:
        LoggingWrapper: A lightweight logging wrapper
    """
    return LoggingWrapper()

