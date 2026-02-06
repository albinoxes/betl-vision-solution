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
import queue
import time
from typing import Optional, Dict, Any, Callable
from datetime import datetime
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


class CsvWriterThread:
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
        self.thread_id = thread_id
        self._csv_queue = queue.Queue(maxsize=200)  # Larger queue for CSV requests
        self._stop_event = threading.Event()
        self._thread = None
        self._running = False
        self._lock = threading.Lock()
        
        # Statistics
        self._stats = {
            'total_queued': 0,
            'total_written': 0,
            'total_failed': 0,
            'queue_size': 0
        }
    
    def start(self) -> bool:
        """
        Start the CSV writer thread.
        
        Returns:
            bool: True if started successfully, False if already running
        """
        with self._lock:
            if self._running:
                logger.warning(f"[{self.thread_id}] CSV writer thread already running")
                return False
            
            self._stop_event.clear()
            self._running = True
            
            # Create and start the thread
            self._thread = threading.Thread(
                target=self._csv_worker,
                name=self.thread_id,
                daemon=True
            )
            self._thread.start()
            
            logger.info(f"[{self.thread_id}] CSV writer thread started")
            return True
    
    def stop(self, timeout: float = 10.0) -> bool:
        """
        Stop the CSV writer thread gracefully.
        
        Args:
            timeout: Maximum time to wait for thread to stop (seconds)
            
        Returns:
            bool: True if stopped successfully
        """
        with self._lock:
            if not self._running:
                logger.info(f"[{self.thread_id}] CSV writer thread already stopped")
                return True
            
            logger.info(f"[{self.thread_id}] Stopping CSV writer thread...")
            self._stop_event.set()
        
        # Wait for thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning(f"[{self.thread_id}] CSV writer thread did not stop within {timeout}s")
                return False
        
        with self._lock:
            self._running = False
        
        logger.info(f"[{self.thread_id}] CSV writer thread stopped successfully")
        logger.info(f"[{self.thread_id}] Final stats: {self._stats}")
        return True
    
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
        if not self._running:
            logger.warning(f"[{self.thread_id}] Cannot queue CSV generation - thread not running")
            return False
        
        try:
            # Create CSV generation request
            request = CsvGenerationRequest(
                project_settings=project_settings,
                timestamp=timestamp,
                data=data,
                folder_type=folder_type,
                image_filename=image_filename,
                callback=callback
            )
            
            # Try to add to queue (non-blocking)
            self._csv_queue.put_nowait(request)
            
            # Update statistics
            with self._lock:
                self._stats['total_queued'] += 1
                self._stats['queue_size'] = self._csv_queue.qsize()
            
            logger.debug(f"[{self.thread_id}] Queued CSV generation for {folder_type} (queue size: {self._csv_queue.qsize()})")
            return True
            
        except queue.Full:
            logger.warning(f"[{self.thread_id}] CSV queue is full, dropping request")
            return False
    
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
                    # No CSV requests in queue, continue loop to check stop event
                    continue
                
                # Process the CSV generation request
                csv_path = None
                try:
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
                        
                        self._stats['queue_size'] = self._csv_queue.qsize()
                    
                    # Call callback if provided
                    if request.callback and csv_path:
                        try:
                            request.callback(csv_path)
                        except Exception as e:
                            logger.error(f"[{self.thread_id}] Error in callback: {e}")
                    
                except Exception as e:
                    logger.error(f"[{self.thread_id}] Error generating CSV: {e}", exc_info=True)
                    with self._lock:
                        self._stats['total_failed'] += 1
                
                finally:
                    # Mark task as done
                    self._csv_queue.task_done()
                
            except Exception as e:
                logger.error(f"[{self.thread_id}] Unexpected error in worker: {e}", exc_info=True)
        
        # Process any remaining items in queue before shutting down
        remaining = self._csv_queue.qsize()
        if remaining > 0:
            logger.info(f"[{self.thread_id}] Processing {remaining} remaining CSV requests before shutdown...")
            
            from iris_communication.iris_input_processor import iris_input_processor
            
            while not self._csv_queue.empty():
                try:
                    request = self._csv_queue.get_nowait()
                    
                    # Generate the CSV
                    try:
                        csv_path = iris_input_processor.generate_iris_input_data(
                            project_settings=request.project_settings,
                            timestamp=request.timestamp,
                            data=request.data,
                            folder_type=request.folder_type,
                            image_filename=request.image_filename
                        )
                        
                        with self._lock:
                            if csv_path:
                                self._stats['total_written'] += 1
                                # Call callback if provided
                                if request.callback:
                                    try:
                                        request.callback(csv_path)
                                    except Exception as e:
                                        logger.error(f"[{self.thread_id}] Error in shutdown callback: {e}")
                            else:
                                self._stats['total_failed'] += 1
                    except Exception as e:
                        logger.error(f"[{self.thread_id}] Error during shutdown CSV generation: {e}")
                        with self._lock:
                            self._stats['total_failed'] += 1
                    finally:
                        self._csv_queue.task_done()
                        
                except queue.Empty:
                    break
        
        logger.info(f"[{self.thread_id}] Worker stopped")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get current statistics about the CSV writer thread.
        
        Returns:
            dict: Statistics including queue size, generation counts, etc.
        """
        with self._lock:
            return self._stats.copy()
    
    def is_running(self) -> bool:
        """
        Check if the CSV writer thread is running.
        
        Returns:
            bool: True if running, False otherwise
        """
        with self._lock:
            return self._running


# Global singleton instance
_csv_writer_instance = None
_instance_lock = threading.Lock()


def get_csv_writer() -> CsvWriterThread:
    """
    Get the global CSV writer singleton instance.
    
    Returns:
        CsvWriterThread: The global CSV writer instance
    """
    global _csv_writer_instance
    
    if _csv_writer_instance is None:
        with _instance_lock:
            if _csv_writer_instance is None:
                _csv_writer_instance = CsvWriterThread()
    
    return _csv_writer_instance
