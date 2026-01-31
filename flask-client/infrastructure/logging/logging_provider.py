import threading
import queue
import os
import inspect
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
                log_data = self._queue.get(timeout=1)
                if log_data is None:  # Sentinel value to stop
                    break
                
                # Unpack log data: (message, thread_name, module_name, function_name)
                message, thread_name, module_name, function_name = log_data
                
                # Write to file with timestamp and context
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                log_entry = f"[{timestamp}] [{thread_name}] [{module_name}.{function_name}] {message}\n"
                self._file_handle.write(log_entry)
                self._file_handle.flush()
                
                self._queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                # Fallback to console if logging fails
                print(f"Logging error: {e}")
    
    def _get_caller_info(self):
        """
        Get information about the calling function (module, function name).
        Skips internal logging methods to get the actual caller.
        """
        # Get the call stack
        stack = inspect.stack()
        
        # Find the first frame outside of logging_provider module
        # Skip frames until we find one that's not in this file
        caller_frame = None
        for frame_info in stack[1:]:  # Skip current function
            frame_module = Path(frame_info.filename).stem
            if frame_module != 'logging_provider':
                caller_frame = frame_info
                break
        
        # If we didn't find an external caller, use the last frame
        if caller_frame is None:
            caller_frame = stack[-1]
        
        # Get module name (controller, processor, etc.)
        module_path = caller_frame.filename
        module_name = Path(module_path).stem  # Get filename without extension
        
        # Get function name
        function_name = caller_frame.function
        
        return module_name, function_name
    
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
        
        # Get thread name and caller information
        thread_name = threading.current_thread().name
        module_name, function_name = self._get_caller_info()
        
        # Put log data as tuple: (message, thread_name, module_name, function_name)
        self._queue.put((str(message), thread_name, module_name, function_name))
    
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
