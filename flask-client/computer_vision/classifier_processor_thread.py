"""
Classifier Processor Thread - Dedicated thread for belt status classification.

This module provides a queue-based classification system that runs in a separate thread.
It ensures that classifier processing doesn't block the camera frame processing thread.

Key Features:
- Single responsibility: Only processes frames with classifiers
- Queue-based: Classification requests are queued and processed asynchronously
- Graceful shutdown: Properly stops when application exits
- Thread-safe: Uses queue.Queue for thread-safe communication
- Memory efficient: Limits queue size to prevent memory issues
"""

import threading
import queue
import time
import numpy as np
from typing import Optional, Dict, Any, Callable
from datetime import datetime
from infrastructure.logging.logging_provider import get_logger

# Initialize logger
logger = get_logger()


class ClassificationRequest:
    """Represents a single frame classification request."""
    
    def __init__(self, frame: np.ndarray, classifier_id: str, timestamp: datetime,
                 project_settings, sftp_server_info, 
                 callback: Optional[Callable[[Any], None]] = None):
        """
        Initialize a classification request.
        
        Args:
            frame: Frame image data (numpy array)
            classifier_id: Classifier model identifier
            timestamp: Processing timestamp
            project_settings: Project settings for CSV generation
            sftp_server_info: SFTP server configuration
            callback: Optional callback function called with classification result
        """
        self.frame = frame
        self.classifier_id = classifier_id
        self.timestamp = timestamp
        self.project_settings = project_settings
        self.sftp_server_info = sftp_server_info
        self.callback = callback
        self.request_time = time.time()


class ClassifierProcessorThread:
    """
    Manages classifier processing in a dedicated background thread.
    
    This class handles all frame classification asynchronously using a queue.
    Classification requests are queued and processed one at a time in the background.
    """
    
    def __init__(self, thread_id: str = "classifier_processor"):
        """
        Initialize the classifier processor thread.
        
        Args:
            thread_id: Unique identifier for the thread
        """
        self.thread_id = thread_id
        self._classification_queue = queue.Queue(maxsize=50)  # Limit to prevent memory issues
        self._stop_event = threading.Event()
        self._thread = None
        self._running = False
        self._lock = threading.Lock()
        
        # Statistics
        self._stats = {
            'total_queued': 0,
            'total_processed': 0,
            'total_failed': 0,
            'total_dropped': 0,  # Frames dropped due to full queue
            'queue_size': 0
        }
    
    def start(self) -> bool:
        """
        Start the classifier processor thread.
        
        Returns:
            bool: True if started successfully, False if already running
        """
        with self._lock:
            if self._running:
                logger.warning(f"[{self.thread_id}] Classifier processor thread already running")
                return False
            
            self._stop_event.clear()
            self._running = True
            
            # Create and start the thread
            self._thread = threading.Thread(
                target=self._classifier_worker,
                name=self.thread_id,
                daemon=True
            )
            self._thread.start()
            
            logger.info(f"[{self.thread_id}] Classifier processor thread started")
            return True
    
    def stop(self, timeout: float = 10.0) -> bool:
        """
        Stop the classifier processor thread gracefully.
        
        Args:
            timeout: Maximum time to wait for thread to stop (seconds)
            
        Returns:
            bool: True if stopped successfully
        """
        with self._lock:
            if not self._running:
                logger.info(f"[{self.thread_id}] Classifier processor thread already stopped")
                return True
            
            logger.info(f"[{self.thread_id}] Stopping classifier processor thread...")
            self._stop_event.set()
        
        # Wait for thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning(f"[{self.thread_id}] Classifier processor thread did not stop within {timeout}s")
                return False
        
        with self._lock:
            self._running = False
        
        logger.info(f"[{self.thread_id}] Classifier processor thread stopped successfully")
        logger.info(f"[{self.thread_id}] Final stats: {self._stats}")
        return True
    
    def queue_classification(self, frame: np.ndarray, classifier_id: str, 
                           timestamp: datetime, project_settings, sftp_server_info,
                           callback: Optional[Callable[[Any], None]] = None) -> bool:
        """
        Queue a frame for classification.
        
        Args:
            frame: Frame image data (numpy array)
            classifier_id: Classifier model identifier
            timestamp: Processing timestamp
            project_settings: Project settings for CSV generation
            sftp_server_info: SFTP server configuration
            callback: Optional callback function called with classification result
            
        Returns:
            bool: True if queued successfully, False if queue is full or thread not running
        """
        if not self._running:
            logger.warning(f"[{self.thread_id}] Cannot queue classification - thread not running")
            return False
        
        try:
            # Create classification request
            request = ClassificationRequest(
                frame=frame.copy(),  # Copy frame to avoid data corruption
                classifier_id=classifier_id,
                timestamp=timestamp,
                project_settings=project_settings,
                sftp_server_info=sftp_server_info,
                callback=callback
            )
            
            # Try to add to queue (non-blocking)
            self._classification_queue.put_nowait(request)
            
            # Update statistics
            with self._lock:
                self._stats['total_queued'] += 1
                self._stats['queue_size'] = self._classification_queue.qsize()
            
            logger.debug(f"[{self.thread_id}] Queued frame for classification (queue size: {self._classification_queue.qsize()})")
            return True
            
        except queue.Full:
            logger.warning(f"[{self.thread_id}] Classification queue is full, dropping frame")
            with self._lock:
                self._stats['total_dropped'] += 1
            return False
    
    def _classifier_worker(self):
        """
        Worker function that processes the classification queue.
        
        This runs in a separate thread and classifies frames one at a time.
        """
        # Import here to avoid circular dependencies
        from computer_vision.classifier_image_processor import classifier_process_image
        from iris_communication.csv_writer_thread import get_csv_writer
        from controllers.camera_controller import create_classifier_csv_callback
        
        logger.info(f"[{self.thread_id}] Worker started, waiting for classification requests...")
        
        csv_writer = get_csv_writer()
        
        while not self._stop_event.is_set():
            try:
                # Wait for classification request with timeout to check stop event periodically
                try:
                    request = self._classification_queue.get(timeout=1.0)
                except queue.Empty:
                    # No classification requests in queue, continue loop to check stop event
                    continue
                
                # Process the classification request
                try:
                    logger.debug(f"[{self.thread_id}] Processing frame with classifier {request.classifier_id}")
                    
                    # Run the classifier
                    belt_status = classifier_process_image(request.frame, classifier_id=request.classifier_id)
                    
                    # Create tracker for CSV callback
                    previous_csv_tracker = {'path': None}
                    
                    # Queue CSV generation with callback
                    csv_writer.queue_csv_generation(
                        project_settings=request.project_settings,
                        timestamp=request.timestamp,
                        data=belt_status,
                        folder_type='classifier',
                        callback=create_classifier_csv_callback(
                            request.sftp_server_info,
                            request.project_settings,
                            previous_csv_tracker
                        )
                    )
                    
                    # Update statistics
                    with self._lock:
                        self._stats['total_processed'] += 1
                        self._stats['queue_size'] = self._classification_queue.qsize()
                    
                    # Call custom callback if provided
                    if request.callback:
                        try:
                            request.callback(belt_status)
                        except Exception as e:
                            logger.error(f"[{self.thread_id}] Error in callback: {e}")
                    
                    logger.debug(f"[{self.thread_id}] Classification complete: {belt_status}")
                    
                except Exception as e:
                    logger.error(f"[{self.thread_id}] Error processing classification: {e}", exc_info=True)
                    with self._lock:
                        self._stats['total_failed'] += 1
                
                finally:
                    # Clean up frame data to free memory
                    del request.frame
                    # Mark task as done
                    self._classification_queue.task_done()
                
            except Exception as e:
                logger.error(f"[{self.thread_id}] Unexpected error in worker: {e}", exc_info=True)
        
        # Process any remaining items in queue before shutting down
        remaining = self._classification_queue.qsize()
        if remaining > 0:
            logger.info(f"[{self.thread_id}] Processing {remaining} remaining frames before shutdown...")
            
            from computer_vision.classifier_image_processor import classifier_process_image
            from iris_communication.csv_writer_thread import get_csv_writer
            from controllers.camera_controller import create_classifier_csv_callback
            
            csv_writer = get_csv_writer()
            
            while not self._classification_queue.empty():
                try:
                    request = self._classification_queue.get_nowait()
                    
                    # Process the classification
                    try:
                        belt_status = classifier_process_image(request.frame, classifier_id=request.classifier_id)
                        
                        previous_csv_tracker = {'path': None}
                        
                        csv_writer.queue_csv_generation(
                            project_settings=request.project_settings,
                            timestamp=request.timestamp,
                            data=belt_status,
                            folder_type='classifier',
                            callback=create_classifier_csv_callback(
                                request.sftp_server_info,
                                request.project_settings,
                                previous_csv_tracker
                            )
                        )
                        
                        with self._lock:
                            self._stats['total_processed'] += 1
                    except Exception as e:
                        logger.error(f"[{self.thread_id}] Error during shutdown classification: {e}")
                        with self._lock:
                            self._stats['total_failed'] += 1
                    finally:
                        del request.frame
                        self._classification_queue.task_done()
                        
                except queue.Empty:
                    break
        
        logger.info(f"[{self.thread_id}] Worker stopped")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get current statistics about the classifier processor thread.
        
        Returns:
            dict: Statistics including queue size, processing counts, etc.
        """
        with self._lock:
            return self._stats.copy()
    
    def is_running(self) -> bool:
        """
        Check if the classifier processor thread is running.
        
        Returns:
            bool: True if running, False otherwise
        """
        with self._lock:
            return self._running


# Global singleton instance
_classifier_processor_instance = None
_instance_lock = threading.Lock()


def get_classifier_processor() -> ClassifierProcessorThread:
    """
    Get the global classifier processor singleton instance.
    
    Returns:
        ClassifierProcessorThread: The global classifier processor instance
    """
    global _classifier_processor_instance
    
    if _classifier_processor_instance is None:
        with _instance_lock:
            if _classifier_processor_instance is None:
                _classifier_processor_instance = ClassifierProcessorThread()
    
    return _classifier_processor_instance
