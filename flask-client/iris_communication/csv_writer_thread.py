"""
CSV Writer Thread - Dedicated thread for generating IRIS CSV files.

This module provides a queue-based CSV generation system that runs in a separate thread.
It ensures that CSV file I/O operations don't block the camera processing thread.

Key Features:
- Single responsibility: Only writes CSV files
- Queue-based: CSV generation requests are queued and processed asynchronously
- Graceful shutdown: Properly stops when application exits
- Thread-safe: Uses queue.Queue for thread-safe communication
- No SFTP coupling: Does not trigger SFTP uploads (that's the SFTP thread's job)
"""

import threading
import time
from typing import Optional, Dict, Any, Callable
from datetime import datetime
from infrastructure.base_queue_thread import BaseQueueThread
from infrastructure.logging.logging_provider import get_logger

# Initialize logger
logger = get_logger()


class CsvGenerationRequest:
    """Represents a single CSV generation request."""
    
    def __init__(self, project_settings, timestamp: datetime, data, 
                 folder_type: str, image_filename: str = None, 
                 callback: Optional[Callable[[str], None]] = None):
        """
        Initialize a CSV generation request.
        
        Args:
            project_settings: Project settings for CSV generation
            timestamp: Timestamp for the CSV data
            data: Data to write to CSV (format depends on folder_type)
            folder_type: Type of data ('model' or 'classifier')
            image_filename: Optional image filename reference
            callback: Optional callback function to call with CSV path when complete
        """
        self.project_settings = project_settings
        self.timestamp = timestamp
        self.data = data
        self.folder_type = folder_type
        self.image_filename = image_filename
        self.callback = callback
        self.request_time = time.time()


class CsvWriterThread(BaseQueueThread):
    """
    Manages CSV generation in a dedicated background thread.
    
    This class handles all CSV file generation asynchronously using a queue.
    CSV generation requests are queued and processed one at a time in the background.
    """
    
    def __init__(self, thread_id: str = "csv_writer"):
        """
        Initialize the CSV writer thread.
        
        Args:
            thread_id: Unique identifier for the thread
        """
        # Initialize base class with larger queue for CSV requests
        super().__init__(thread_id=thread_id, queue_maxsize=200)
    
    def _initialize_stats(self) -> Dict[str, Any]:
        """Initialize CSV-specific statistics."""
        return {
            'total_queued': 0,
            'total_processed': 0,
            'total_written': 0,  # CSV-specific: successful writes
            'total_failed': 0,
            'queue_size': 0
        }
    
    def _get_queue_timeout(self) -> float:
        """Return timeout for queue.get() calls."""
        return 1.0
    
    def queue_csv_generation(self, project_settings, timestamp: datetime, data,
                            folder_type: str, image_filename: str = None,
                            callback: Optional[Callable[[str], None]] = None) -> bool:
        """
        Queue a CSV generation request.
        
        Args:
            project_settings: Project settings for CSV generation
            timestamp: Timestamp for the CSV data
            data: Data to write to CSV
            folder_type: Type of data ('model' or 'classifier')
            image_filename: Optional image filename reference
            callback: Optional callback function called with CSV path when complete
            
        Returns:
            bool: True if queued successfully, False if queue is full or thread not running
        """
        # Create CSV generation request
        request = CsvGenerationRequest(
            project_settings=project_settings,
            timestamp=timestamp,
            data=data,
            folder_type=folder_type,
            image_filename=image_filename,
            callback=callback
        )
        
        # Use base class queue_item method
        return self.queue_item(request)
    
    def _csv_worker(self):
        """
        Worker function that processes the CSV generation queue.
        
        This runs in a separate thread and generates CSV files one at a time.
        """
        # Import here to avoid circular dependencies
        from iris_communication.iris_input_processor import iris_input_processor
        
        logger.info(f"[{self.thread_id}] Worker started, waiting for CSV generation requests...")
        
        while not self._stop_event.is_set():
            try:
                # Wait for CSV generation request with timeout to check stop event periodically
                try:
                    request = self._csv_queue.get(timeout=1.0)
                except queue.Empty:
         process_item(self, request: CsvGenerationRequest):
        """
        Process a single CSV generation request.
        
        Args:
            request: CSV generation request to process
        """
        # Import here to avoid circular dependencies
        from iris_communication.iris_input_processor import iris_input_processor
        
        logger.debug(f"[{self.thread_id}] Generating CSV for {request.folder_type}")
        
        # Generate the CSV file
        csv_path = iris_input_processor.generate_iris_input_data(
            project_settings=request.project_settings,
            timestamp=request.timestamp,
            data=request.data,
            folder_type=request.folder_type,
            image_filename=request.image_filename
        )
        
        # Update statistics
        with self._lock:
            if csv_path:
                self._stats['total_written'] += 1
                logger.info(f"[{self.thread_id}] CSV written: {csv_path}")
            else:
                self._stats['total_failed'] += 1
                logger.warning(f"[{self.thread_id}] CSV generation returned None")
        
        # Call callback if provided
        if request.callback and csv_path:
            try:
                request.callback(csv_path)
            except Exception as e:
                logger.error(f"[{self.thread_id}] Error in callback: {e}")one:
        with _instance_lock:
            if _csv_writer_instance is None:
                _csv_writer_instance = CsvWriterThread()
    
    return _csv_writer_instance
