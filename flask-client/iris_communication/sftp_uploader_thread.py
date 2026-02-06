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
import time
from typing import Optional, Dict, Any
from infrastructure.base_queue_thread import BaseQueueThread
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


class SftpUploaderThread(BaseQueueThread):
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
        # Initialize base class with queue size limit
        super().__init__(thread_id=thread_id, queue_maxsize=100)
    
    def _initialize_stats(self) -> Dict[str, Any]:
        """Initialize SFTP-specific statistics."""
        return {
            'total_queued': 0,
            'total_processed': 0,
            'total_uploaded': 0,  # SFTP-specific: successful uploads
            'total_failed': 0,
            'queue_size': 0
        }
    
    def _get_queue_timeout(self) -> float:
        """Return timeout for queue.get() calls."""
        return 1.0
    
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
        # Create upload request
        request = SftpUploadRequest(
            sftp_server_info=sftp_server_info,
            file_path=file_path,
            project_settings=project_settings,
            folder_type=folder_type
        )
        
        # Use base class queue_item method
        return self.queue_item(request)
    
    def _process_item(self, request: SftpUploadRequest):
        """
        Process a single SFTP upload request.
        
        Args:
            request: SFTP upload request to process
        """
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
