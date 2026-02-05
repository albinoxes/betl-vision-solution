import logging
import threading
import inspect
import queue
import atexit
import gc
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler, QueueHandler, QueueListener


class LoggingProvider:
    """
    Singleton logging provider with non-blocking async writes.
    Uses queue-based logging to prevent blocking on I/O operations.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(LoggingProvider, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        
        # Create logs directory if it doesn't exist
        self._logs_dir = Path(__file__).parent.parent.parent / 'logs'
        self._logs_dir.mkdir(exist_ok=True)
        
        # Create log file with current timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self._log_file_path = self._logs_dir / f'logs_{timestamp}.txt'
        
        # Create logger
        self._logger = logging.getLogger('BeltVisionApp')
        self._logger.setLevel(logging.DEBUG)
        
        # Prevent duplicate handlers
        if self._logger.handlers:
            self._logger.handlers.clear()
        
        # Create rotating file handler (10MB max, keep 5 backup files)
        file_handler = RotatingFileHandler(
            self._log_file_path,
            maxBytes=10*1024*1024,  # 10 MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        
        # Create custom formatter
        formatter = CustomFormatter()
        file_handler.setFormatter(formatter)
        
        # Create a queue for async logging
        self._log_queue = queue.Queue(maxsize=10000)  # Limit queue size to prevent unbounded growth
        
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
        
    def start(self):
        """Start the async logging listener."""
        if not self._listener_started:
            self._queue_listener.start()
            self._listener_started = True
            self._logger.info(f"Async logging started - Log file: {self._log_file_path}")
    
    def log(self, message):
        """
        Add a log message without a specific level.
        
        Args:
            message: The message to log
        """
        self._logger.info(message)
    
    def info(self, message):
        """Log an info message."""
        self._logger.info(message)
    
    def error(self, message, exc_info=False):
        """
        Log an error message.
        
        Args:
            message: Error message to log
            exc_info: If True, includes exception traceback
        """
        self._logger.error(message, exc_info=exc_info)
    
    def warning(self, message):
        """Log a warning message."""
        self._logger.warning(message)
    
    def debug(self, message):
        """Log a debug message."""
        self._logger.debug(message)
    
    def _cleanup(self):
        """Internal cleanup method."""
        if self._listener_started:
            try:
                # Stop queue listener (processes remaining messages)
                self._queue_listener.stop()
                self._listener_started = False
                
                # Close and flush file handler
                if self._file_handler:
                    self._file_handler.flush()
                    self._file_handler.close()
                
                # Clear queue to free memory
                while not self._log_queue.empty():
                    try:
                        self._log_queue.get_nowait()
                    except queue.Empty:
                        break
                
                # Force garbage collection
                gc.collect()
                
            except Exception as e:
                # Fallback to print if logging fails during cleanup
                print(f"Error during logging cleanup: {e}")
    
    def stop(self):
        """Stop the logging and flush handlers."""
        self._logger.info("Logging stopped")
        self._cleanup()
    
    def get_queue_size(self):
        """Get current queue size for monitoring."""
        return self._log_queue.qsize()
    
    def get_stats(self):
        """Get logging statistics."""
        return {
            'queue_size': self._log_queue.qsize(),
            'queue_maxsize': self._log_queue.maxsize,
            'log_file': str(self._log_file_path),
            'listener_running': self._listener_started
        }


class CustomFormatter(logging.Formatter):
    """
    Custom formatter that outputs logs in the format:
    [YYYY-MM-DD HH:MM:SS] [LEVEL] [ThreadName] [module.function] message
    """
    
    def format(self, record):
        # Get timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')
        
        # Get level
        level = record.levelname
        
        # Get thread name
        thread_name = record.threadName
        
        # Get caller information (module.function)
        module_name = Path(record.pathname).stem
        function_name = record.funcName
        
        # Build log entry
        log_entry = f"[{timestamp}] [{level}] [{thread_name}] [{module_name}.{function_name}] {record.getMessage()}"
        
        # Add exception info if present
        if record.exc_info:
            log_entry += '\n' + self.formatException(record.exc_info)
        
        return log_entry


# Convenience function to get the singleton instance
def get_logger():
    """Get the singleton LoggingProvider instance."""
    return LoggingProvider()

