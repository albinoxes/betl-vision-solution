"""!
@file model_detector_thread.py
@brief Model Detector Thread - Dedicated thread for object detection processing.

@details
This module provides a queue-based object detection system that runs in a separate thread.
It ensures that model detection doesn't block the camera frame processing thread.

Key Features:
- Single responsibility: Only processes frames with object detection models
- Queue-based: Detection requests are queued and processed asynchronously
- Graceful shutdown: Properly stops when application exits
- Thread-safe: Uses queue.Queue for thread-safe communication
- Memory efficient: Limits queue size to prevent memory issues

@author Belt Vision Team
@date 2026-02-06
"""

import threading
import time
import numpy as np
from typing import Optional, Dict, Any, Callable
from datetime import datetime
from infrastructure.base_queue_thread import BaseQueueThread
from infrastructure.logging.logging_provider import get_logger

# Initialize logger
logger = get_logger()


class DetectionRequest:
    """!
    @brief Represents a single frame detection request.
    
    @details
    This class encapsulates all information needed to process a frame through
    the object detection pipeline. It includes the frame data, model configuration,
    and callback mechanisms for asynchronous processing.
    """
    
    def __init__(self, frame: np.ndarray, model, settings, model_id: str, 
                 timestamp: datetime, image_filename: str, project_settings, 
                 sftp_server_info, callback: Optional[Callable[[Any], None]] = None):
        """!
        @brief Initialize a detection request.
        
        @param frame Frame image data as numpy array
        @param model Loaded YOLO detection model instance
        @param settings Camera settings object for detection configuration
        @param model_id Unique identifier for the detection model
        @param timestamp Processing timestamp (datetime object)
        @param image_filename Reference path to saved image file
        @param project_settings Project settings for CSV generation and metadata
        @param sftp_server_info SFTP server configuration for file uploads
        @param callback Optional callback function called with detection result (default: None)
        
        @note The frame is copied when queued to avoid data corruption from concurrent access.
        @see ModelDetectorThread.queue_detection()
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


class ModelDetectorThread(BaseQueueThread):
    """!
    @brief Manages object detection processing in a dedicated background thread.
    
    @details
    This class handles all frame detection asynchronously using a queue-based system.
    Detection requests are queued and processed one at a time in the background thread,
    preventing object detection inference from blocking the camera frame processing.
    
    Thread Safety:
    - Uses queue.Queue for thread-safe communication
    - Threading.Lock protects statistics and state
    - Event-based shutdown for graceful termination
    
    Queue Management:
    - Maximum queue size: 50 frames
    - Frames dropped when queue is full
    - Remaining frames processed during shutdown
    
    @note This class follows the singleton pattern via get_model_detector()
    @see get_model_detector()
    """
    
    def __init__(self, thread_id: str = "model_detector"):
        """!
        @brief Initialize the model detector thread.
        
        @param thread_id Unique identifier for the thread (default: "model_detector")
        
        @note Creates queue with maxsize=50 to prevent memory issues
        @note Statistics tracking includes: total_queued, total_processed, total_failed, total_dropped
        """
        # Initialize base class with queue size limit
        super().__init__(thread_id=thread_id, queue_maxsize=50)
    
    def _initialize_stats(self) -> Dict[str, Any]:
        """Initialize model detector-specific statistics."""
        return {
            'total_queued': 0,
            'total_processed': 0,
            'total_failed': 0,
            'total_dropped': 0,  # Frames dropped due to full queue
            'queue_size': 0
        }
    
    def _get_queue_timeout(self) -> float:
        """Return timeout for queue.get() calls."""
        return 1.0
    
    def queue_detection(self, frame: np.ndarray, model, settings, model_id: str,
                       timestamp: datetime, image_filename: str, project_settings, 
                       sftp_server_info, callback: Optional[Callable[[Any], None]] = None) -> bool:
        """!
        @brief Queue a frame for object detection.
        
        @param frame Frame image data as numpy array
        @param model Loaded YOLO detection model instance
        @param settings Camera settings object for detection configuration
        @param model_id Unique identifier for the detection model
        @param timestamp Processing timestamp (datetime object)
        @param image_filename Reference path to saved image file
        @param project_settings Project settings for CSV generation and metadata
        @param sftp_server_info SFTP server configuration for file uploads
        @param callback Optional callback function called with detection result (default: None)
        
        @return True if queued successfully, False if queue is full or thread not running
        
        @note Frame is copied to avoid data corruption from concurrent modifications
        @note Uses put_nowait() - returns False immediately if queue is full
        @warning Returns False if thread is not running - call start() first
        @warning Increments total_dropped statistic when queue is full
        
        @code{.py}
        detector = get_model_detector()
        if detector.queue_detection(frame, model, settings, model_id, 
                                   datetime.now(), img_path, project_cfg, sftp_cfg):
            print("Detection queued successfully")
        else:
            print("Failed to queue - queue full or thread not running")
        @endcode
        
        @see DetectionRequest, _detector_worker()
        """
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
        
        # Use base class queue_item method
        success = self.queue_item(request)
        
        # Track dropped frames if queue was full
        if not success and self.is_running():
            with self._lock:
                self._stats['total_dropped'] += 1
        
        return success
    
    def _process_item(self, request: DetectionRequest):
        """!
        @brief Process a single detection request.
        
        @param request Detection request to process
        
        @details
        This method performs object detection using the ml_model_image_processor module.
        
        Processing Flow:
        1. Run object detection via object_process_image()
        2. Extract particles_to_detect (index 2) for CSV generation
        3. Queue CSV generation with SFTP upload callback
        4. Call custom callback if provided
        5. Clean up frame data to free memory
        
        @see object_process_image(), create_model_csv_callback()
        """
        # Import here to avoid circular dependencies
        from computer_vision.ml_model_image_processor import object_process_image
        from iris_communication.csv_writer_thread import get_csv_writer
        from controllers.camera_controller import create_model_csv_callback
        
        logger.debug(f"[{self.thread_id}] Processing frame with model {request.model_id}")
        
        # Run object detection
        result = object_process_image(request.frame, model=request.model, settings=request.settings)
        
        # result format: [image, xyxy, particles_to_detect, particles_to_save]
        # Use particles_to_detect (index 2) for CSV/reporting
        result_for_csv = [result[0], result[1], result[2]]
        
        # Create tracker for CSV callback
        previous_csv_tracker = {'path': None}
        
        # Queue CSV generation with callback
        csv_writer = get_csv_writer()
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
        
        # Call custom callback if provided
        if request.callback:
            try:
                request.callback(result)
            except Exception as e:
                logger.error(f"[{self.thread_id}] Error in callback: {e}")
        
        logger.debug(f"[{self.thread_id}] Detection complete, found {len(result[1])} objects")
        
        # Clean up frame data to free memory
        del request.frame
    
    def get_stats(self) -> Dict[str, Any]:
        """!
        @brief Get current statistics about the model detector thread.
        
        @return Dictionary containing statistics:
                - total_queued: Total frames queued for detection
                - total_processed: Total frames successfully processed
                - total_failed: Total frames that failed processing
                - total_dropped: Total frames dropped due to full queue
                - queue_size: Current number of frames in queue
        
        @note Thread-safe: uses lock to ensure consistent snapshot
        @note Returns a copy of statistics to prevent external modification
        
        @code{.py}
        detector = get_model_detector()
        stats = detector.get_stats()
        print(f"Queue size: {stats['queue_size']}")
        print(f"Success rate: {stats['total_processed']}/{stats['total_queued']}")
        @endcode
        """
        with self._lock:
            return self._stats.copy()
    
    def is_running(self) -> bool:
        """!
        @brief Check if the model detector thread is running.
        
        @return True if running, False otherwise
        
        @note Thread-safe: uses lock to check running state
        
        @code{.py}
        detector = get_model_detector()
        if not detector.is_running():
            detector.start()
        @endcode
        """
        with self._lock:
            return self._running


# Global singleton instance
_model_detector_instance = None
_instance_lock = threading.Lock()


def get_model_detector() -> ModelDetectorThread:
    """!
    @brief Get the global model detector singleton instance.
    
    @return The global ModelDetectorThread singleton instance
    
    @note Thread-safe: uses double-checked locking pattern
    @note Creates instance on first call (lazy initialization)
    @warning Always use this function instead of creating ModelDetectorThread() directly
    
    @code{.py}
    # Correct usage - get singleton instance
    detector = get_model_detector()
    detector.start()
    
    # Incorrect - creates separate instance
    # detector = ModelDetectorThread()  # DON'T DO THIS
    @endcode
    
    @see ModelDetectorThread
    """
    global _model_detector_instance
    
    if _model_detector_instance is None:
        with _instance_lock:
            if _model_detector_instance is None:
                _model_detector_instance = ModelDetectorThread()
    
    return _model_detector_instance
