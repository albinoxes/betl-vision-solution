import threading
import queue
import os
from datetime import datetime
from pathlib import Path


class LoggingProvider:
    """
    Singleton logging provider that writes logs to a text file in a separate thread.
    A new log file is created each time the application starts with the format: logs_{creation_date}.txt
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
        self._queue = queue.Queue()
        self._running = False
        self._worker_thread = None
        self._log_file_path = None
        self._file_handle = None
        
        # Create logs directory if it doesn't exist
        self._logs_dir = Path(__file__).parent.parent.parent / 'logs'
        self._logs_dir.mkdir(exist_ok=True)
        
        # Create log file with current timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self._log_file_path = self._logs_dir / f'logs_{timestamp}.txt'
        
    def start(self):
        """Start the logging worker thread."""
        if self._running:
            return
        
        self._running = True
        self._file_handle = open(self._log_file_path, 'a', encoding='utf-8')
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()
        
        # Log the initialization
        self.log(f"Logging started - Log file: {self._log_file_path}")
    
    def _worker(self):
        """Worker thread that processes log messages from the queue."""
        while self._running:
            try:
                # Wait for log message with timeout to allow checking _running flag
                message = self._queue.get(timeout=1)
                if message is None:  # Sentinel value to stop
                    break
                
                # Write to file with timestamp
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                log_entry = f"[{timestamp}] {message}\n"
                self._file_handle.write(log_entry)
                self._file_handle.flush()
                
                self._queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                # Fallback to console if logging fails
                print(f"Logging error: {e}")
    
    def log(self, message):
        """
        Add a log message to the queue.
        
        Args:
            message: The message to log (can be any type, will be converted to string)
        """
        if not self._running:
            # If not started yet, just print to console
            print(message)
            return
        
        self._queue.put(str(message))
    
    def info(self, message):
        """Log an info message."""
        self.log(f"INFO: {message}")
    
    def error(self, message):
        """Log an error message."""
        self.log(f"ERROR: {message}")
    
    def warning(self, message):
        """Log a warning message."""
        self.log(f"WARNING: {message}")
    
    def debug(self, message):
        """Log a debug message."""
        self.log(f"DEBUG: {message}")
    
    def stop(self):
        """Stop the logging worker thread and close the file."""
        if not self._running:
            return
        
        self.log("Logging stopped")
        self._running = False
        self._queue.put(None)  # Sentinel value
        
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
        
        if self._file_handle:
            self._file_handle.close()
    
    def __del__(self):
        """Ensure cleanup when object is destroyed."""
        self.stop()


# Convenience function to get the singleton instance
def get_logger():
    """Get the singleton LoggingProvider instance."""
    return LoggingProvider()
