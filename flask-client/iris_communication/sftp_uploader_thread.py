"""
SFTP Uploader Thread - Dedicated thread for handling SFTP file uploads.

This module provides a queue-based SFTP upload system that runs in a separate thread.
It ensures that SFTP operations don't block the main camera processing thread.

Key Features:
- Single responsibility: Only handles SFTP uploads
- Queue-based: Upload requests are queued and processed asynchronously
- Graceful shutdown: Properly stops when application exits
- Thread-safe: Uses queue.Queue for thread-safe communication
"""

import threading
import queue
import time
from typing import Optional, Dict, Any
from infrastructure.logging.logging_provider import get_logger
from iris_communication.sftp_processor import sftp_processor
from sqlite.sftp_sqlite_provider import SftpServerInfos

# Initialize logger
logger = get_logger()


class SftpUploadRequest:
    """Represents a single SFTP upload request."""
    
    def __init__(self, sftp_server_info: SftpServerInfos, file_path: str, 
                 project_settings, folder_type: str):
        """
        Initialize an upload request.
        
        Args:
            sftp_server_info: SFTP server credentials and connection info
            file_path: Local file path to upload
            project_settings: Project settings for determining remote paths
            folder_type: Type of data ('model' or 'classifier')
        """
        self.sftp_server_info = sftp_server_info
        self.file_path = file_path
        self.project_settings = project_settings
        self.folder_type = folder_type
        self.timestamp = time.time()


class SftpUploaderThread:
    """
    Manages SFTP uploads in a dedicated background thread.
    
    This class handles all SFTP upload operations asynchronously using a queue.
    Upload requests are queued and processed one at a time in the background.
    """
    
    def __init__(self, thread_id: str = "sftp_uploader"):
        """
        Initialize the SFTP uploader thread.
        
        Args:
            thread_id: Unique identifier for the thread
        """
        self.thread_id = thread_id
        self._upload_queue = queue.Queue(maxsize=100)  # Limit queue size
        self._stop_event = threading.Event()
        self._thread = None
        self._running = False
        self._lock = threading.Lock()
        
        # Statistics
        self._stats = {
            'total_queued': 0,
            'total_uploaded': 0,
            'total_failed': 0,
            'queue_size': 0
        }
    
    def start(self) -> bool:
        """
        Start the SFTP uploader thread.
        
        Returns:
            bool: True if started successfully, False if already running
        """
        with self._lock:
            if self._running:
                logger.warning(f"[{self.thread_id}] SFTP uploader thread already running")
                return False
            
            self._stop_event.clear()
            self._running = True
            
            # Create and start the thread
            self._thread = threading.Thread(
                target=self._upload_worker,
                name=self.thread_id,
                daemon=True
            )
            self._thread.start()
            
            logger.info(f"[{self.thread_id}] SFTP uploader thread started")
            return True
    
    def stop(self, timeout: float = 10.0) -> bool:
        """
        Stop the SFTP uploader thread gracefully.
        
        Args:
            timeout: Maximum time to wait for thread to stop (seconds)
            
        Returns:
            bool: True if stopped successfully
        """
        with self._lock:
            if not self._running:
                logger.info(f"[{self.thread_id}] SFTP uploader thread already stopped")
                return True
            
            logger.info(f"[{self.thread_id}] Stopping SFTP uploader thread...")
            self._stop_event.set()
        
        # Wait for thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning(f"[{self.thread_id}] SFTP uploader thread did not stop within {timeout}s")
                return False
        
        with self._lock:
            self._running = False
        
        logger.info(f"[{self.thread_id}] SFTP uploader thread stopped successfully")
        logger.info(f"[{self.thread_id}] Final stats: {self._stats}")
        return True
    
    def queue_upload(self, sftp_server_info: SftpServerInfos, file_path: str,
                     project_settings, folder_type: str) -> bool:
        """
        Queue a file for SFTP upload.
        
        Args:
            sftp_server_info: SFTP server credentials and connection info
            file_path: Local file path to upload
            project_settings: Project settings for determining remote paths
            folder_type: Type of data ('model' or 'classifier')
            
        Returns:
            bool: True if queued successfully, False if queue is full or thread not running
        """
        if not self._running:
            logger.warning(f"[{self.thread_id}] Cannot queue upload - thread not running")
            return False
        
        try:
            # Create upload request
            request = SftpUploadRequest(
                sftp_server_info=sftp_server_info,
                file_path=file_path,
                project_settings=project_settings,
                folder_type=folder_type
            )
            
            # Try to add to queue (non-blocking)
            self._upload_queue.put_nowait(request)
            
            # Update statistics
            with self._lock:
                self._stats['total_queued'] += 1
                self._stats['queue_size'] = self._upload_queue.qsize()
            
            logger.debug(f"[{self.thread_id}] Queued upload: {file_path} (queue size: {self._upload_queue.qsize()})")
            return True
            
        except queue.Full:
            logger.warning(f"[{self.thread_id}] Upload queue is full, dropping request for {file_path}")
            return False
    
    def _upload_worker(self):
        """
        Worker function that processes the upload queue.
        
        This runs in a separate thread and processes uploads one at a time.
        """
        logger.info(f"[{self.thread_id}] Worker started, waiting for upload requests...")
        
        while not self._stop_event.is_set():
            try:
                # Wait for upload request with timeout to check stop event periodically
                try:
                    request = self._upload_queue.get(timeout=1.0)
                except queue.Empty:
                    # No uploads in queue, continue loop to check stop event
                    continue
                
                # Process the upload request
                try:
                    logger.info(f"[{self.thread_id}] Processing upload: {request.file_path}")
                    
                    # Perform the actual SFTP upload
                    result = sftp_processor.transferData(
                        sftp_server_info=request.sftp_server_info,
                        file_path=request.file_path,
                        project_settings=request.project_settings,
                        folder_type=request.folder_type
                    )
                    
                    # Update statistics based on result
                    with self._lock:
                        if result.get('success'):
                            self._stats['total_uploaded'] += 1
                            logger.info(f"[{self.thread_id}] Successfully uploaded: {result.get('remote_path')}")
                        else:
                            self._stats['total_failed'] += 1
                            logger.error(f"[{self.thread_id}] Upload failed: {result.get('error', 'Unknown error')}")
                        
                        self._stats['queue_size'] = self._upload_queue.qsize()
                    
                except Exception as e:
                    logger.error(f"[{self.thread_id}] Error processing upload: {e}", exc_info=True)
                    with self._lock:
                        self._stats['total_failed'] += 1
                
                finally:
                    # Mark task as done
                    self._upload_queue.task_done()
                
            except Exception as e:
                logger.error(f"[{self.thread_id}] Unexpected error in worker: {e}", exc_info=True)
        
        # Process any remaining items in queue before shutting down
        remaining = self._upload_queue.qsize()
        if remaining > 0:
            logger.info(f"[{self.thread_id}] Processing {remaining} remaining uploads before shutdown...")
            
            while not self._upload_queue.empty():
                try:
                    request = self._upload_queue.get_nowait()
                    
                    # Process the upload
                    try:
                        result = sftp_processor.transferData(
                            sftp_server_info=request.sftp_server_info,
                            file_path=request.file_path,
                            project_settings=request.project_settings,
                            folder_type=request.folder_type
                        )
                        
                        with self._lock:
                            if result.get('success'):
                                self._stats['total_uploaded'] += 1
                            else:
                                self._stats['total_failed'] += 1
                    except Exception as e:
                        logger.error(f"[{self.thread_id}] Error during shutdown upload: {e}")
                        with self._lock:
                            self._stats['total_failed'] += 1
                    finally:
                        self._upload_queue.task_done()
                        
                except queue.Empty:
                    break
        
        logger.info(f"[{self.thread_id}] Worker stopped")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get current statistics about the uploader thread.
        
        Returns:
            dict: Statistics including queue size, upload counts, etc.
        """
        with self._lock:
            return self._stats.copy()
    
    def is_running(self) -> bool:
        """
        Check if the uploader thread is running.
        
        Returns:
            bool: True if running, False otherwise
        """
        with self._lock:
            return self._running


# Global singleton instance
_sftp_uploader_instance = None
_instance_lock = threading.Lock()


def get_sftp_uploader() -> SftpUploaderThread:
    """
    Get the global SFTP uploader singleton instance.
    
    Returns:
        SftpUploaderThread: The global SFTP uploader instance
    """
    global _sftp_uploader_instance
    
    if _sftp_uploader_instance is None:
        with _instance_lock:
            if _sftp_uploader_instance is None:
                _sftp_uploader_instance = SftpUploaderThread()
    
    return _sftp_uploader_instance
