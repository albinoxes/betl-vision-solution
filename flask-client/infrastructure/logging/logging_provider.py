import logging
import threading
import inspect
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler


class LoggingProvider:
    """
    Singleton logging provider using Python's logging library.
    Creates rotating log files with custom formatting.
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
        
        # Add handler to logger
        self._logger.addHandler(file_handler)
        
    def start(self):
        """Start the logging (for compatibility with old interface)."""
        self._logger.info(f"Logging started - Log file: {self._log_file_path}")
    
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
    
    def error(self, message):
        """Log an error message."""
        self._logger.error(message)
    
    def warning(self, message):
        """Log a warning message."""
        self._logger.warning(message)
    
    def debug(self, message):
        """Log a debug message."""
        self._logger.debug(message)
    
    def stop(self):
        """Stop the logging and flush handlers."""
        self._logger.info("Logging stopped")
        for handler in self._logger.handlers:
            handler.flush()
            handler.close()


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

