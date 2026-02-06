"""
Base Queue Thread - Abstract base class for queue-based background processing threads.

This module provides a reusable base class that encapsulates common thread management patterns
used throughout the application. It handles lifecycle management, queue processing, statistics
tracking, and graceful shutdown.

Key Features:
- Thread lifecycle management (start, stop)
- Queue-based processing with configurable limits
- Statistics tracking
- Graceful shutdown with timeout
- Thread-safe operations
- Memory leak prevention
- Extensible via template method pattern
"""

import threading
import queue
import time
from typing import Dict, Any, Optional
from abc import ABC, abstractmethod
from infrastructure.logging.logging_provider import get_logger

logger = get_logger()


class BaseQueueThread(ABC):
    """
    Abstract base class for managing queue-based background processing threads.
    
    This class implements the common patterns used by all queue-based worker threads:
    - Queue management with configurable size limits
    - Thread lifecycle (start, stop, status tracking)
    - Statistics collection
    - Graceful shutdown handling
    - Thread-safe operations
    
    Subclasses must implement:
    - _process_item(item): Process a single queue item
    - _get_queue_timeout(): Return timeout for queue.get() calls
    
    Subclasses may override:
    - _initialize_stats(): Define custom statistics keys
    - _on_start(): Called when thread starts
    - _on_stop(): Called when thread stops
    - _on_item_queued(): Called when item is queued successfully
    - _on_item_processed(): Called after item is processed successfully
    - _on_item_failed(exception): Called when item processing fails
    """
    
    def __init__(self, thread_id: str, queue_maxsize: int = 100):
        """
        Initialize the base queue thread.
        
        Args:
            thread_id: Unique identifier for the thread
            queue_maxsize: Maximum size of the processing queue (default: 100)
        """
        self.thread_id = thread_id
        self._queue = queue.Queue(maxsize=queue_maxsize)
        self._stop_event = threading.Event()
        self._thread = None
        self._running = False
        self._lock = threading.Lock()
        
        # Initialize statistics
        self._stats = self._initialize_stats()
    
    def _initialize_stats(self) -> Dict[str, Any]:
        """
        Initialize statistics dictionary.
        
        Override this method to add custom statistics keys.
        
        Returns:
            dict: Initial statistics dictionary
        """
        return {
            'total_queued': 0,
            'total_processed': 0,
            'total_failed': 0,
            'queue_size': 0
        }
    
    def start(self) -> bool:
        """
        Start the background processing thread.
        
        Returns:
            bool: True if started successfully, False if already running
        """
        with self._lock:
            if self._running:
                logger.warning(f"[{self.thread_id}] Thread already running")
                return False
            
            self._stop_event.clear()
            self._running = True
            
            # Create and start the thread
            self._thread = threading.Thread(
                target=self._worker,
                name=self.thread_id,
                daemon=True
            )
            self._thread.start()
            
            logger.info(f"[{self.thread_id}] Thread started")
            self._on_start()
            return True
    
    def stop(self, timeout: float = 10.0) -> bool:
        """
        Stop the background processing thread gracefully.
        
        Args:
            timeout: Maximum time to wait for thread to stop (seconds)
            
        Returns:
            bool: True if stopped successfully, False if timeout occurred
        """
        with self._lock:
            if not self._running:
                logger.info(f"[{self.thread_id}] Thread already stopped")
                return True
            
            logger.info(f"[{self.thread_id}] Stopping thread...")
            self._stop_event.set()
        
        # Wait for thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning(f"[{self.thread_id}] Thread did not stop within {timeout}s")
                return False
        
        with self._lock:
            self._running = False
        
        logger.info(f"[{self.thread_id}] Thread stopped successfully")
        logger.info(f"[{self.thread_id}] Final stats: {self._stats}")
        self._on_stop()
        return True
    
    def queue_item(self, item: Any) -> bool:
        """
        Queue an item for processing.
        
        Args:
            item: Item to queue for processing
            
        Returns:
            bool: True if queued successfully, False if queue is full or thread not running
        """
        if not self._running:
            logger.warning(f"[{self.thread_id}] Cannot queue item - thread not running")
            return False
        
        try:
            # Try to add to queue (non-blocking)
            self._queue.put_nowait(item)
            
            # Update statistics
            with self._lock:
                self._stats['total_queued'] += 1
                self._stats['queue_size'] = self._queue.qsize()
            
            self._on_item_queued(item)
            logger.debug(f"[{self.thread_id}] Item queued (queue size: {self._queue.qsize()})")
            return True
            
        except queue.Full:
            logger.warning(f"[{self.thread_id}] Queue is full, dropping item")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get current thread statistics.
        
        Returns:
            dict: Copy of current statistics
        """
        with self._lock:
            # Update queue size
            self._stats['queue_size'] = self._queue.qsize()
            return self._stats.copy()
    
    def is_running(self) -> bool:
        """
        Check if the thread is currently running.
        
        Returns:
            bool: True if thread is running, False otherwise
        """
        with self._lock:
            return self._running
    
    def get_queue_size(self) -> int:
        """
        Get the current queue size.
        
        Returns:
            int: Number of items in the queue
        """
        return self._queue.qsize()
    
    def _worker(self):
        """
        Worker function that processes the queue.
        
        This runs in a separate thread and processes items one at a time.
        """
        logger.info(f"[{self.thread_id}] Worker started, waiting for items...")
        
        while not self._stop_event.is_set():
            try:
                # Wait for item with timeout to check stop event periodically
                try:
                    item = self._queue.get(timeout=self._get_queue_timeout())
                except queue.Empty:
                    # No items in queue, continue loop to check stop event
                    continue
                
                # Process the item
                try:
                    logger.debug(f"[{self.thread_id}] Processing item...")
                    start_time = time.time()
                    
                    # Call the subclass-specific processing method
                    self._process_item(item)
                    
                    processing_time = time.time() - start_time
                    
                    # Update statistics
                    with self._lock:
                        self._stats['total_processed'] += 1
                    
                    self._on_item_processed(item, processing_time)
                    logger.debug(f"[{self.thread_id}] Item processed in {processing_time:.3f}s")
                    
                except Exception as e:
                    # Update failure statistics
                    with self._lock:
                        self._stats['total_failed'] += 1
                    
                    self._on_item_failed(item, e)
                    logger.error(f"[{self.thread_id}] Failed to process item: {str(e)}", exc_info=True)
                
                finally:
                    # Mark task as done
                    self._queue.task_done()
                    
            except Exception as e:
                logger.error(f"[{self.thread_id}] Unexpected error in worker loop: {str(e)}", exc_info=True)
        
        # Process remaining items in queue before shutting down
        self._process_remaining_items()
        
        logger.info(f"[{self.thread_id}] Worker stopped")
    
    def _process_remaining_items(self):
        """
        Process all remaining items in the queue before shutdown.
        """
        remaining = self._queue.qsize()
        if remaining > 0:
            logger.info(f"[{self.thread_id}] Processing {remaining} remaining items...")
            
            while not self._queue.empty():
                try:
                    item = self._queue.get_nowait()
                    try:
                        self._process_item(item)
                        with self._lock:
                            self._stats['total_processed'] += 1
                    except Exception as e:
                        with self._lock:
                            self._stats['total_failed'] += 1
                        logger.error(f"[{self.thread_id}] Failed to process remaining item: {str(e)}")
                    finally:
                        self._queue.task_done()
                except queue.Empty:
                    break
    
    # Abstract methods that subclasses must implement
    
    @abstractmethod
    def _process_item(self, item: Any):
        """
        Process a single queue item.
        
        This method must be implemented by subclasses to define their specific processing logic.
        
        Args:
            item: Item to process
            
        Raises:
            Exception: Any exception raised will be caught and logged
        """
        pass
    
    @abstractmethod
    def _get_queue_timeout(self) -> float:
        """
        Get the timeout for queue.get() calls.
        
        This method must be implemented by subclasses to define how long to wait
        for items in the queue before checking the stop event.
        
        Returns:
            float: Timeout in seconds (typically 0.5 to 2.0 seconds)
        """
        pass
    
    # Optional hook methods that subclasses can override
    
    def _on_start(self):
        """Called when the thread starts. Override to add custom startup logic."""
        pass
    
    def _on_stop(self):
        """Called when the thread stops. Override to add custom cleanup logic."""
        pass
    
    def _on_item_queued(self, item: Any):
        """Called when an item is successfully queued. Override to add custom logic."""
        pass
    
    def _on_item_processed(self, item: Any, processing_time: float):
        """Called after an item is successfully processed. Override to add custom logic."""
        pass
    
    def _on_item_failed(self, item: Any, exception: Exception):
        """Called when item processing fails. Override to add custom error handling."""
        pass
