## @file classifier_processor_thread.py
#  @brief Classifier processor thread for asynchronous belt status classification.
#
#  This module provides a dedicated thread for processing belt classification requests
#  asynchronously. It uses a queue-based system to prevent blocking the camera frame
#  processing thread and ensures memory-efficient operation with configurable limits.
#
#  @author Belt Vision Team
#  @date 2026

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
    """@brief Represents a single frame classification request.
    
    This class encapsulates all the data needed to perform a classification operation
    on a single frame, including the frame data, classifier settings, and callback
    information for post-processing.
    """
    
    def __init__(self, frame: np.ndarray, classifier_id: str, timestamp: datetime,
                 project_settings, sftp_server_info, 
                 callback: Optional[Callable[[Any], None]] = None):
        """@brief Initialize a classification request.
        
        @param frame Frame image data as numpy array (will be copied to prevent data corruption)
        @param classifier_id Classifier model identifier for the classification operation
        @param timestamp Processing timestamp to associate with the classification result
        @param project_settings Project settings used for CSV generation after classification
        @param sftp_server_info SFTP server configuration for uploading results
        @param callback Optional callback function called with classification result when complete
        
        @note The frame is copied when queued to prevent race conditions with the camera thread
        """
        self.frame = frame
        self.classifier_id = classifier_id
        self.timestamp = timestamp
        self.project_settings = project_settings
        self.sftp_server_info = sftp_server_info
        self.callback = callback
        self.request_time = time.time()


class ClassifierProcessorThread:
    """@brief Manages classifier processing in a dedicated background thread.
    
    This class implements a queue-based asynchronous classification system that processes
    frames independently from the camera thread. It maintains statistics, handles graceful
    shutdown, and provides thread-safe access to processing status.
    
    The thread processes classification requests one at a time from a bounded queue,
    automatically generating CSV files via the CSV writer thread upon completion.
    
    @note This is a singleton class - use get_classifier_processor() to obtain the instance
    """
    
    def __init__(self, thread_id: str = "classifier_processor"):
        """@brief Initialize the classifier processor thread.
        
        Creates the internal queue, synchronization primitives, and statistics tracking.
        Does not start the thread - call start() to begin processing.
        
        @param thread_id Unique identifier for the thread (default: "classifier_processor")
        
        @note Queue is limited to 50 frames to prevent memory exhaustion
        @note Statistics track: total_queued, total_processed, total_failed, total_dropped, queue_size
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
        """@brief Start the classifier processor thread.
        
        Creates and starts a daemon thread that processes classification requests from the queue.
        The thread runs the _classifier_worker method which handles the actual classification.
        
        @return True if started successfully, False if already running
        
        @note Thread is created as daemon to ensure it doesn't prevent application shutdown
        @note Thread-safe operation using internal lock
        
        @see stop()
        @see _classifier_worker()
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
        """@brief Stop the classifier processor thread gracefully.
        
        Signals the worker thread to stop and waits for it to finish processing remaining
        items in the queue. Processes all queued classifications before shutdown to prevent
        data loss.
        
        @param timeout Maximum time in seconds to wait for thread to stop (default: 10.0)
        
        @return True if stopped successfully, False if timeout occurred
        
        @note Any items remaining in queue will be processed before thread exits
        @note Logs final statistics upon successful shutdown
        
        @warning If timeout occurs, thread may still be running and holding resources
        
        @see start()
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
        """@brief Queue a frame for classification.
        
        Adds a classification request to the processing queue. The frame is copied to prevent
        data corruption from concurrent access. If the queue is full, the frame is dropped and
        the drop counter is incremented.
        
        @param frame Frame image data as numpy array to classify
        @param classifier_id Classifier model identifier to use for classification
        @param timestamp Processing timestamp to associate with results
        @param project_settings Project settings for CSV generation
        @param sftp_server_info SFTP server configuration for result upload
        @param callback Optional callback function called with classification result
        
        @return True if queued successfully, False if queue is full or thread not running
        
        @note Frame is copied internally to prevent race conditions
        @note Non-blocking operation - returns immediately
        @note Updates total_queued and queue_size statistics on success
        @note Updates total_dropped statistics if queue is full
        
        @warning Returns False if thread is not running - check with is_running() first
        
        @code
        # Queue a frame for classification
        success = classifier_processor.queue_classification(
            frame=current_frame,
            classifier_id="belt_status_v1",
            timestamp=datetime.now(),
            project_settings=settings,
            sftp_server_info=sftp_config
        )
        if not success:
            logger.warning("Failed to queue classification")
        @endcode
        
        @see ClassificationRequest
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
        """@brief Worker function that processes the classification queue.
        
        This internal method runs in a separate thread and continuously processes classification
        requests from the queue. For each request, it:
        1. Runs the classifier on the frame
        2. Queues CSV generation via the CSV writer thread
        3. Calls any custom callback if provided
        4. Updates statistics
        5. Cleans up frame memory
        
        The worker processes remaining queue items during shutdown to prevent data loss.
        
        @note Runs in separate daemon thread - do not call directly
        @note Imports are done locally to avoid circular dependencies
        @note Automatically generates CSV files and triggers SFTP uploads via callbacks
        @note Gracefully handles errors without crashing the thread
        
        @warning Frame memory is explicitly deleted to prevent memory leaks
        
        @see queue_classification()
        @see ClassificationRequest
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
        """@brief Get current statistics about the classifier processor thread.
        
        Returns a copy of the internal statistics dictionary containing processing metrics.
        Thread-safe operation using internal lock.
        
        @return Dictionary with keys:
                - total_queued: Total number of frames queued for classification
                - total_processed: Total number of frames successfully classified
                - total_failed: Total number of classification failures
                - total_dropped: Total number of frames dropped due to full queue
                - queue_size: Current number of frames waiting in queue
        
        @note Returns a copy to prevent external modification of internal state
        @note Thread-safe operation
        
        @code
        stats = classifier_processor.get_stats()
        print(f"Queue size: {stats['queue_size']}")
        print(f"Success rate: {stats['total_processed'] / stats['total_queued'] * 100:.1f}%")
        @endcode
        """
        with self._lock:
            return self._stats.copy()
    
    def is_running(self) -> bool:
        """@brief Check if the classifier processor thread is running.
        
        Thread-safe check of the thread's running state.
        
        @return True if thread is running and processing requests, False otherwise
        
        @note Thread-safe operation using internal lock
        @note Returns False if thread was never started or has been stopped
        
        @see start()
        @see stop()
        """
        with self._lock:
            return self._running


# Global singleton instance
_classifier_processor_instance = None
_instance_lock = threading.Lock()


def get_classifier_processor() -> ClassifierProcessorThread:
    """@brief Get the global classifier processor singleton instance.
    
    Returns the singleton instance of ClassifierProcessorThread, creating it if necessary.
    Thread-safe creation using double-checked locking pattern.
    
    @return The global ClassifierProcessorThread singleton instance
    
    @note This function implements the singleton pattern - same instance returned on all calls
    @note Thread-safe initialization using lock
    @note Instance is created on first call (lazy initialization)
    
    @code
    # Get the classifier processor instance
    classifier_processor = get_classifier_processor()
    
    # Start if not already running
    if not classifier_processor.is_running():
        classifier_processor.start()
    
    # Queue a frame for classification
    classifier_processor.queue_classification(
        frame=frame_data,
        classifier_id="belt_status_v2",
        timestamp=datetime.now(),
        project_settings=proj_settings,
        sftp_server_info=sftp_info
    )
    @endcode
    
    @see ClassifierProcessorThread
    """
    global _classifier_processor_instance
    
    if _classifier_processor_instance is None:
        with _instance_lock:
            if _classifier_processor_instance is None:
                _classifier_processor_instance = ClassifierProcessorThread()
    
    return _classifier_processor_instance
