##
# @file logging_provider.py
# @brief Logging provider module for Belt Vision application
# @details This module provides a singleton logging provider using Python's logging library
#          with rotating file handlers and custom formatting.
# @author Belt Vision Team
# @date 2026-02-01

import logging
import threading
import queue
import atexit
import gc
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler, QueueHandler, QueueListener


##
# @class LoggingProvider
# @brief Singleton logging provider with rotating file support
# @details Implements a thread-safe singleton pattern for application-wide logging.
#          Creates rotating log files (10MB max, 5 backups) with custom formatting
#          in the format: [YYYY-MM-DD HH:MM:SS] [LEVEL] [ThreadName] [module.function] message
class LoggingProvider:
    ## @brief Singleton instance of LoggingProvider
    _instance = None

    ## @brief Thread lock for thread-safe singleton instantiation
    _lock = threading.Lock()

    ##
    # @brief Create or return the singleton instance
    # @param cls The class reference
    # @return The singleton instance of LoggingProvider
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(LoggingProvider, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    ##
    # @brief Initialize the logging provider
    # @details Sets up the logs directory, creates a timestamped log file,
    #          configures the logger with a rotating file handler and custom formatter.
    #          Uses double-checked locking to ensure single initialization.
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        
        self._logs_dir = Path(__file__).parent.parent.parent / 'logs'
        self._logs_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self._log_file_path = self._logs_dir / f'logs_{timestamp}.txt'
        
        self._logger = logging.getLogger('BeltVisionApp')
        self._logger.setLevel(logging.DEBUG)
        
        if self._logger.handlers:
            self._logger.handlers.clear()
        
        file_handler = RotatingFileHandler(
            self._log_file_path,
            maxBytes=10*1024*1024,  # 10 MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        
        formatter = CustomFormatter()
        file_handler.setFormatter(formatter)
        
        # Create a queue for async logging
        self._log_queue = queue.Queue(maxsize=10000)
        
        # Create QueueHandler to send logs to the queue (non-blocking)
        queue_handler = QueueHandler(self._log_queue)
        self._logger.addHandler(queue_handler)
        
        # Create QueueListener to process logs from queue in background thread
        self._queue_listener = QueueListener(
            self._log_queue,
            file_handler,
            respect_handler_level=True
        )
        
        # Track if listener is started
        self._listener_started = False
        
        # Keep reference to file handler for cleanup
        self._file_handler = file_handler
        
        # Register cleanup on exit
        atexit.register(self._cleanup)
        
    ##
    # @brief Start the logging service
    # @details Logs an initial message indicating the logging has started.
    #          Provided for compatibility with the old logging interface.
    # @return None
    def start(self):
        if not self._listener_started:
            self._queue_listener.start()
            self._listener_started = True
            self._logger.info(f"Async logging started - Log file: {self._log_file_path}")
    
    def log(self, message):
        self._logger.info(message)
    
    def info(self, message):
        self._logger.info(message)
    
    def error(self, message, exc_info=False):
        self._logger.error(message, exc_info=exc_info)
    
    def warning(self, message):
        self._logger.warning(message)
    
    def debug(self, message):
        self._logger.debug(message)
    
    ##
    # @brief Cleanup the logging service
    # @details Stop and Clear the logging queue
    # @return None
    def _cleanup(self):
        if self._listener_started:
            try:
                self._queue_listener.stop()
                self._listener_started = False
                
                if self._file_handler:
                    self._file_handler.flush()
                    self._file_handler.close()
                
                while not self._log_queue.empty():
                    try:
                        self._log_queue.get_nowait()
                    except queue.Empty:
                        break
                
                gc.collect()
                
            except Exception as e:
                print(f"Error during logging cleanup: {e}")
    
    ##
    # @brief Stop the logging service
    # @details Launch the cleanung private method
    # @return None
    def stop(self):
        self._logger.info("Logging stopped")
        self._cleanup()
    
    def get_queue_size(self):
        """Get current queue size for monitoring."""
        return self._log_queue.qsize()
    
    def get_stats(self):
        return {
            'queue_size': self._log_queue.qsize(),
            'queue_maxsize': self._log_queue.maxsize,
            'log_file': str(self._log_file_path),
            'listener_running': self._listener_started
        }

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
# @brief Get the singleton LoggingProvider instance
# @details Convenience function to obtain the global logging provider instance.
#          Creates the instance if it doesn't exist.
# @return The singleton LoggingProvider instance
def get_logger():
    """Get the singleton LoggingProvider instance."""
    return LoggingProvider()

