"""
Thread Manager for managing background processing threads.

This module provides centralized thread lifecycle management to prevent memory leaks
and ensure proper resource cleanup.
"""

import threading
import time
from typing import Dict, Callable, Optional, Any
from infrastructure.logging.logging_provider import get_logger

logger = get_logger()


class ThreadManager:
    """
    Manages background processing threads with proper lifecycle management.
    
    Features:
    - Thread creation and tracking
    - Graceful shutdown
    - Resource cleanup
    - Memory leak prevention
    - Thread health monitoring
    """
    
    def __init__(self):
        """Initialize the thread manager."""
        self._threads: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._cleanup_interval = 60  # seconds before removing stopped threads from tracking
    
    def start_thread(
        self,
        thread_id: str,
        target: Callable,
        args: tuple = (),
        kwargs: dict = None,
        metadata: dict = None
    ) -> bool:
        """
        Start a new managed thread.
        
        Args:
            thread_id: Unique identifier for the thread
            target: Function to run in the thread
            args: Positional arguments for the target function
            kwargs: Keyword arguments for the target function
            metadata: Optional metadata to store with the thread
            
        Returns:
            bool: True if thread started successfully, False if already exists
        """
        if kwargs is None:
            kwargs = {}
        if metadata is None:
            metadata = {}
            
        with self._lock:
            # Check if thread already exists and is running
            if thread_id in self._threads and self._threads[thread_id]['running']:
                logger.warning(f"[ThreadManager] Thread {thread_id} already running")
                return False
            
            # Create the thread
            thread = threading.Thread(
                target=self._thread_wrapper,
                args=(thread_id, target, args, kwargs),
                daemon=True,
                name=thread_id
            )
            
            # Track the thread
            self._threads[thread_id] = {
                'thread': thread,
                'running': True,
                'status': 'starting',
                'start_time': time.time(),
                'last_update': time.time(),
                'metadata': metadata
            }
            
            # Start the thread
            thread.start()
            logger.info(f"[ThreadManager] Started thread: {thread_id}")
            return True
    
    def _thread_wrapper(
        self,
        thread_id: str,
        target: Callable,
        args: tuple,
        kwargs: dict
    ):
        """
        Wrapper function that runs the target function and handles cleanup.
        
        Args:
            thread_id: Unique identifier for the thread
            target: Function to run
            args: Positional arguments
            kwargs: Keyword arguments
        """
        try:
            # Update status to running
            with self._lock:
                if thread_id in self._threads:
                    self._threads[thread_id]['status'] = 'running'
            
            # Execute the target function
            target(*args, **kwargs)
            
        except Exception as e:
            logger.error(f"[ThreadManager] Error in thread {thread_id}: {e}", exc_info=True)
            with self._lock:
                if thread_id in self._threads:
                    self._threads[thread_id]['status'] = f'error: {str(e)[:50]}'
        finally:
            # Mark thread as stopped
            with self._lock:
                if thread_id in self._threads:
                    self._threads[thread_id]['running'] = False
                    self._threads[thread_id]['status'] = 'stopped'
                    self._threads[thread_id]['last_update'] = time.time()
            
            logger.info(f"[ThreadManager] Thread {thread_id} finished")
    
    def stop_thread(self, thread_id: str, timeout: float = 5.0) -> bool:
        """
        Stop a managed thread gracefully.
        
        Args:
            thread_id: Unique identifier for the thread
            timeout: Maximum time to wait for thread to stop (seconds)
            
        Returns:
            bool: True if thread stopped successfully or already stopped, False if thread exists but won't stop
        """
        thread_obj = None
        already_stopped = False
        
        with self._lock:
            if thread_id not in self._threads:
                logger.info(f"[ThreadManager] Thread {thread_id} not found (likely already stopped and cleaned up)")
                return True  # Thread doesn't exist = already stopped = success
            
            # Check if already stopped
            if not self._threads[thread_id]['running']:
                logger.info(f"[ThreadManager] Thread {thread_id} already stopped")
                already_stopped = True
            
            # Immediately signal the thread to stop
            self._threads[thread_id]['running'] = False
            self._threads[thread_id]['status'] = 'stopping'
            thread_obj = self._threads[thread_id].get('thread')
        
        # If already stopped, just return success
        if already_stopped:
            logger.info(f"[ThreadManager] Thread {thread_id} was already stopped, returning success")
            return True
        
        logger.info(f"[ThreadManager] Stopping thread {thread_id}...")
        logger.info(f"[ThreadManager] Running flag set to False immediately")
        
        # Wait for thread to stop
        if thread_obj and thread_obj.is_alive():
            thread_obj.join(timeout=timeout)
            if thread_obj.is_alive():
                logger.warning(f"[ThreadManager] Thread {thread_id} did not stop within {timeout}s")
                return False
            else:
                logger.info(f"[ThreadManager] Thread {thread_id} stopped successfully")
        else:
            logger.info(f"[ThreadManager] Thread {thread_id} is not alive, marking as stopped")
        
        # Update status
        with self._lock:
            if thread_id in self._threads:
                self._threads[thread_id]['status'] = 'stopped'
                self._threads[thread_id]['last_update'] = time.time()
        
        return True
    
    def stop_all_threads(self, timeout: float = 5.0):
        """
        Stop all managed threads.
        
        Args:
            timeout: Maximum time to wait for each thread to stop (seconds)
        """
        thread_ids = []
        with self._lock:
            # First, set ALL threads to not running immediately
            for thread_id in self._threads:
                self._threads[thread_id]['running'] = False
                self._threads[thread_id]['status'] = 'stopping'
            thread_ids = list(self._threads.keys())
        
        logger.info(f"[ThreadManager] Stopping all {len(thread_ids)} threads...")
        logger.info(f"[ThreadManager] All running flags set to False")
        
        # Now wait for each thread
        for thread_id in thread_ids:
            thread_obj = None
            with self._lock:
                if thread_id in self._threads:
                    thread_obj = self._threads[thread_id].get('thread')
            
            if thread_obj and thread_obj.is_alive():
                logger.info(f"[ThreadManager] Waiting for thread {thread_id} to stop...")
                thread_obj.join(timeout=timeout / len(thread_ids))  # Distribute timeout
                if thread_obj.is_alive():
                    logger.warning(f"[ThreadManager] Thread {thread_id} did not stop within timeout")
                else:
                    logger.info(f"[ThreadManager] Thread {thread_id} stopped")
            
            # Update status
            with self._lock:
                if thread_id in self._threads:
                    self._threads[thread_id]['status'] = 'stopped'
                    self._threads[thread_id]['last_update'] = time.time()
    
    def is_running(self, thread_id: str) -> bool:
        """
        Check if a thread is currently running.
        
        Args:
            thread_id: Unique identifier for the thread
            
        Returns:
            bool: True if thread is running, False otherwise
        """
        with self._lock:
            if thread_id not in self._threads:
                return False
            return self._threads[thread_id]['running']
    
    def get_thread_info(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a specific thread.
        
        Args:
            thread_id: Unique identifier for the thread
            
        Returns:
            dict: Thread information or None if not found
        """
        with self._lock:
            if thread_id not in self._threads:
                return None
            
            info = self._threads[thread_id].copy()
            # Don't include the thread object in the returned info
            info.pop('thread', None)
            # Calculate uptime
            info['uptime'] = int(time.time() - info['start_time'])
            return info
    
    def get_all_threads(self) -> Dict[str, Dict[str, Any]]:
        """
        Get information about all managed threads.
        
        Returns:
            dict: Dictionary of thread_id -> thread_info
        """
        with self._lock:
            all_threads = {}
            for thread_id, info in self._threads.items():
                thread_info = info.copy()
                thread_info.pop('thread', None)
                thread_info['uptime'] = int(time.time() - info['start_time'])
                all_threads[thread_id] = thread_info
            return all_threads
    
    def update_metadata(self, thread_id: str, metadata: dict):
        """
        Update metadata for a thread.
        
        Args:
            thread_id: Unique identifier for the thread
            metadata: Metadata to update (will be merged with existing)
        """
        with self._lock:
            if thread_id in self._threads:
                self._threads[thread_id]['metadata'].update(metadata)
                self._threads[thread_id]['last_update'] = time.time()
    
    def set_status(self, thread_id: str, status: str):
        """
        Set the status of a thread.
        
        Args:
            thread_id: Unique identifier for the thread
            status: New status string
        """
        with self._lock:
            if thread_id in self._threads:
                self._threads[thread_id]['status'] = status
                self._threads[thread_id]['last_update'] = time.time()
    
    def cleanup_stopped_threads(self, max_age: Optional[float] = None):
        """
        Remove stopped threads from tracking after they've been stopped for a while.
        
        Args:
            max_age: Maximum age in seconds before cleanup (default: self._cleanup_interval)
        """
        if max_age is None:
            max_age = self._cleanup_interval
        
        current_time = time.time()
        to_remove = []
        
        with self._lock:
            for thread_id, info in self._threads.items():
                if not info['running'] and (current_time - info.get('last_update', 0) > max_age):
                    to_remove.append(thread_id)
            
            for thread_id in to_remove:
                del self._threads[thread_id]
                logger.debug(f"[ThreadManager] Cleaned up stopped thread: {thread_id}")
        
        if to_remove:
            logger.info(f"[ThreadManager] Cleaned up {len(to_remove)} stopped threads")
    
    def get_active_count(self) -> int:
        """
        Get the number of currently running threads.
        
        Returns:
            int: Number of active threads
        """
        with self._lock:
            return sum(1 for t in self._threads.values() if t['running'])
    
    def get_total_count(self) -> int:
        """
        Get the total number of tracked threads.
        
        Returns:
            int: Total number of threads
        """
        with self._lock:
            return len(self._threads)


# Global singleton instance
_thread_manager_instance = None
_instance_lock = threading.Lock()


def get_thread_manager() -> ThreadManager:
    """
    Get the global ThreadManager singleton instance.
    
    Returns:
        ThreadManager: The global thread manager instance
    """
    global _thread_manager_instance
    
    if _thread_manager_instance is None:
        with _instance_lock:
            if _thread_manager_instance is None:
                _thread_manager_instance = ThreadManager()
    
    return _thread_manager_instance
