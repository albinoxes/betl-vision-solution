"""
Model Detector Thread - Dedicated thread for object detection processing.

This module provides a queue-based object detection system that runs in a separate thread.
It ensures that model detection doesn't block the camera frame processing thread.

Key Features:
- Single responsibility: Only processes frames with object detection models
- Queue-based: Detection requests are queued and processed asynchronously
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


class DetectionRequest:
    """Represents a single frame detection request."""
    
    def __init__(self, frame: np.ndarray, model, settings, model_id: str, 
                 timestamp: datetime, image_filename: str, project_settings, 
                 sftp_server_info, callback: Optional[Callable[[Any], None]] = None):
        """
        Initialize a detection request.
        
        Args:
            frame: Frame image data (numpy array)
            model: Loaded detection model
            settings: Camera settings for detection
            model_id: Model identifier
            timestamp: Processing timestamp
            image_filename: Reference to saved image file
            project_settings: Project settings for CSV generation
            sftp_server_info: SFTP server configuration
            callback: Optional callback function called with detection result
        """
        self.frame = frame
        self.model = model
        self.settings = settings
        self.model_id = model_id
        self.timestamp = timestamp
        self.image_filename = image_filename
        self.project_settings = project_settings
        self.sftp_server_info = sftp_server_info
        self.callback = callback
        self.request_time = time.time()


class ModelDetectorThread:
    """
    Manages object detection processing in a dedicated background thread.
    
    This class handles all frame detection asynchronously using a queue.
    Detection requests are queued and processed one at a time in the background.
    """
    
    def __init__(self, thread_id: str = "model_detector"):
        """
        Initialize the model detector thread.
        
        Args:
            thread_id: Unique identifier for the thread
        """
        self.thread_id = thread_id
        self._detection_queue = queue.Queue(maxsize=50)  # Limit to prevent memory issues
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
        Start the model detector thread.
        
        Returns:
            bool: True if started successfully, False if already running
        """
        with self._lock:
            if self._running:
                logger.warning(f"[{self.thread_id}] Model detector thread already running")
                return False
            
            self._stop_event.clear()
            self._running = True
            
            # Create and start the thread
            self._thread = threading.Thread(
                target=self._detector_worker,
                name=self.thread_id,
                daemon=True
            )
            self._thread.start()
            
            logger.info(f"[{self.thread_id}] Model detector thread started")
            return True
    
    def stop(self, timeout: float = 10.0) -> bool:
        """
        Stop the model detector thread gracefully.
        
        Args:
            timeout: Maximum time to wait for thread to stop (seconds)
            
        Returns:
            bool: True if stopped successfully
        """
        with self._lock:
            if not self._running:
                logger.info(f"[{self.thread_id}] Model detector thread already stopped")
                return True
            
            logger.info(f"[{self.thread_id}] Stopping model detector thread...")
            self._stop_event.set()
        
        # Wait for thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning(f"[{self.thread_id}] Model detector thread did not stop within {timeout}s")
                return False
        
        with self._lock:
            self._running = False
        
        logger.info(f"[{self.thread_id}] Model detector thread stopped successfully")
        logger.info(f"[{self.thread_id}] Final stats: {self._stats}")
        return True
    
    def queue_detection(self, frame: np.ndarray, model, settings, model_id: str,
                       timestamp: datetime, image_filename: str, project_settings, 
                       sftp_server_info, callback: Optional[Callable[[Any], None]] = None) -> bool:
        """
        Queue a frame for object detection.
        
        Args:
            frame: Frame image data (numpy array)
            model: Loaded detection model
            settings: Camera settings for detection
            model_id: Model identifier
            timestamp: Processing timestamp
            image_filename: Reference to saved image file
            project_settings: Project settings for CSV generation
            sftp_server_info: SFTP server configuration
            callback: Optional callback function called with detection result
            
        Returns:
            bool: True if queued successfully, False if queue is full or thread not running
        """
        if not self._running:
            logger.warning(f"[{self.thread_id}] Cannot queue detection - thread not running")
            return False
        
        try:
            # Create detection request
            request = DetectionRequest(
                frame=frame.copy(),  # Copy frame to avoid data corruption
                model=model,
                settings=settings,
                model_id=model_id,
                timestamp=timestamp,
                image_filename=image_filename,
                project_settings=project_settings,
                sftp_server_info=sftp_server_info,
                callback=callback
            )
            
            # Try to add to queue (non-blocking)
            self._detection_queue.put_nowait(request)
            
            # Update statistics
            with self._lock:
                self._stats['total_queued'] += 1
                self._stats['queue_size'] = self._detection_queue.qsize()
            
            logger.debug(f"[{self.thread_id}] Queued frame for detection (queue size: {self._detection_queue.qsize()})")
            return True
            
        except queue.Full:
            logger.warning(f"[{self.thread_id}] Detection queue is full, dropping frame")
            with self._lock:
                self._stats['total_dropped'] += 1
            return False
    
    def _detector_worker(self):
        """
        Worker function that processes the detection queue.
        
        This runs in a separate thread and detects objects in frames one at a time.
        """
        # Import here to avoid circular dependencies
        from computer_vision.ml_model_image_processor import object_process_image
        from iris_communication.csv_writer_thread import get_csv_writer
        from controllers.camera_controller import create_model_csv_callback
        
        logger.info(f"[{self.thread_id}] Worker started, waiting for detection requests...")
        
        csv_writer = get_csv_writer()
        
        while not self._stop_event.is_set():
            try:
                # Wait for detection request with timeout to check stop event periodically
                try:
                    request = self._detection_queue.get(timeout=1.0)
                except queue.Empty:
                    # No detection requests in queue, continue loop to check stop event
                    continue
                
                # Process the detection request
                try:
                    logger.debug(f"[{self.thread_id}] Processing frame with model {request.model_id}")
                    
                    # Run object detection
                    result = object_process_image(request.frame, model=request.model, settings=request.settings)
                    
                    # result format: [image, xyxy, particles_to_detect, particles_to_save]
                    # Use particles_to_detect (index 2) for CSV/reporting
                    result_for_csv = [result[0], result[1], result[2]]
                    
                    # Create tracker for CSV callback
                    previous_csv_tracker = {'path': None}
                    
                    # Queue CSV generation with callback
                    csv_writer.queue_csv_generation(
                        project_settings=request.project_settings,
                        timestamp=request.timestamp,
                        data=result_for_csv,
                        folder_type='model',
                        image_filename=request.image_filename,
                        callback=create_model_csv_callback(
                            request.sftp_server_info,
                            request.project_settings,
                            previous_csv_tracker
                        )
                    )
                    
                    # Update statistics
                    with self._lock:
                        self._stats['total_processed'] += 1
                        self._stats['queue_size'] = self._detection_queue.qsize()
                    
                    # Call custom callback if provided
                    if request.callback:
                        try:
                            request.callback(result)
                        except Exception as e:
                            logger.error(f"[{self.thread_id}] Error in callback: {e}")
                    
                    logger.debug(f"[{self.thread_id}] Detection complete, found {len(result[1])} objects")
                    
                except Exception as e:
                    logger.error(f"[{self.thread_id}] Error processing detection: {e}", exc_info=True)
                    with self._lock:
                        self._stats['total_failed'] += 1
                
                finally:
                    # Clean up frame data to free memory
                    del request.frame
                    # Mark task as done
                    self._detection_queue.task_done()
                
            except Exception as e:
                logger.error(f"[{self.thread_id}] Unexpected error in worker: {e}", exc_info=True)
        
        # Process any remaining items in queue before shutting down
        remaining = self._detection_queue.qsize()
        if remaining > 0:
            logger.info(f"[{self.thread_id}] Processing {remaining} remaining frames before shutdown...")
            
            from computer_vision.ml_model_image_processor import object_process_image
            from iris_communication.csv_writer_thread import get_csv_writer
            from controllers.camera_controller import create_model_csv_callback
            
            csv_writer = get_csv_writer()
            
            while not self._detection_queue.empty():
                try:
                    request = self._detection_queue.get_nowait()
                    
                    # Process the detection
                    try:
                        result = object_process_image(request.frame, model=request.model, settings=request.settings)
                        result_for_csv = [result[0], result[1], result[2]]
                        
                        previous_csv_tracker = {'path': None}
                        
                        csv_writer.queue_csv_generation(
                            project_settings=request.project_settings,
                            timestamp=request.timestamp,
                            data=result_for_csv,
                            folder_type='model',
                            image_filename=request.image_filename,
                            callback=create_model_csv_callback(
                                request.sftp_server_info,
                                request.project_settings,
                                previous_csv_tracker
                            )
                        )
                        
                        with self._lock:
                            self._stats['total_processed'] += 1
                    except Exception as e:
                        logger.error(f"[{self.thread_id}] Error during shutdown detection: {e}")
                        with self._lock:
                            self._stats['total_failed'] += 1
                    finally:
                        del request.frame
                        self._detection_queue.task_done()
                        
                except queue.Empty:
                    break
        
        logger.info(f"[{self.thread_id}] Worker stopped")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get current statistics about the model detector thread.
        
        Returns:
            dict: Statistics including queue size, processing counts, etc.
        """
        with self._lock:
            return self._stats.copy()
    
    def is_running(self) -> bool:
        """
        Check if the model detector thread is running.
        
        Returns:
            bool: True if running, False otherwise
        """
        with self._lock:
            return self._running


# Global singleton instance
_model_detector_instance = None
_instance_lock = threading.Lock()


def get_model_detector() -> ModelDetectorThread:
    """
    Get the global model detector singleton instance.
    
    Returns:
        ModelDetectorThread: The global model detector instance
    """
    global _model_detector_instance
    
    if _model_detector_instance is None:
        with _instance_lock:
            if _model_detector_instance is None:
                _model_detector_instance = ModelDetectorThread()
    
    return _model_detector_instance
