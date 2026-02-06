"""
Socket Manager for managing HTTP connections between services.

This module provides centralized socket/connection management to prevent memory leaks,
socket exhaustion, and ensure proper resource cleanup.
"""

import requests
import threading
import time
from typing import Dict, Optional, Any, Generator
from urllib.parse import urlparse
from infrastructure.logging.logging_provider import get_logger

logger = get_logger()


class SocketManager:
    """
    Manages HTTP connections and sockets with proper lifecycle management.
    
    Features:
    - Connection pooling for performance
    - Automatic timeout management
    - Proper connection cleanup
    - Socket leak prevention
    - Connection tracking and monitoring
    - Graceful shutdown
    """
    
    def __init__(
        self,
        max_connections_per_host: int = 10,
        max_total_connections: int = 50,
        default_timeout: tuple = (5, 30),  # (connect_timeout, read_timeout)
        stream_timeout: tuple = (10, 60)   # Longer read timeout for continuous video streams
    ):
        """
        Initialize the socket manager.
        
        Args:
            max_connections_per_host: Maximum connections per host
            max_total_connections: Maximum total connections
            default_timeout: Default (connect, read) timeout in seconds
            stream_timeout: Timeout for streaming connections
        """
        self._sessions: Dict[str, requests.Session] = {}
        self._active_streams: Dict[str, Any] = {}
        self._lock = threading.Lock()
        
        # Configuration
        self.max_connections_per_host = max_connections_per_host
        self.max_total_connections = max_total_connections
        self.default_timeout = default_timeout
        self.stream_timeout = stream_timeout
        
        # Statistics
        self._stats = {
            'requests_made': 0,
            'streams_opened': 0,
            'connections_closed': 0,
            'errors': 0
        }
    
    def _get_session(self, base_url: str) -> requests.Session:
        """
        Get or create a session for a specific host.
        
        Args:
            base_url: Base URL to get session for
            
        Returns:
            requests.Session: Session object for the host
        """
        parsed = urlparse(base_url)
        host_key = f"{parsed.scheme}://{parsed.netloc}"
        
        with self._lock:
            if host_key not in self._sessions:
                session = requests.Session()
                
                # Configure connection pooling
                adapter = requests.adapters.HTTPAdapter(
                    pool_connections=self.max_connections_per_host,
                    pool_maxsize=self.max_connections_per_host,
                    max_retries=0,  # No automatic retries
                    pool_block=False
                )
                
                session.mount('http://', adapter)
                session.mount('https://', adapter)
                
                self._sessions[host_key] = session
                logger.debug(f"[SocketManager] Created new session for {host_key}")
            
            return self._sessions[host_key]
    
    def get(
        self,
        url: str,
        timeout: Optional[tuple] = None,
        **kwargs
    ) -> requests.Response:
        """
        Make a GET request with proper connection management.
        
        Args:
            url: URL to request
            timeout: Optional (connect, read) timeout tuple
            **kwargs: Additional arguments for requests.get()
            
        Returns:
            requests.Response: Response object
        """
        session = self._get_session(url)
        
        if timeout is None:
            timeout = self.default_timeout
        
        try:
            with self._lock:
                self._stats['requests_made'] += 1
            
            response = session.get(url, timeout=timeout, **kwargs)
            return response
            
        except Exception as e:
            with self._lock:
                self._stats['errors'] += 1
            logger.error(f"[SocketManager] Error in GET {url}: {e}")
            raise
    
    def stream(
        self,
        stream_id: str,
        url: str,
        timeout: Optional[tuple] = None,
        chunk_size: int = 8192
    ) -> Generator[bytes, None, None]:
        """
        Create a streaming connection with automatic cleanup.
        
        Args:
            stream_id: Unique identifier for this stream
            url: URL to stream from
            timeout: Optional (connect, read) timeout tuple
            chunk_size: Size of chunks to yield
            
        Yields:
            bytes: Chunks of data from the stream
        """
        session = self._get_session(url)
        
        if timeout is None:
            timeout = self.stream_timeout
        
        response = None
        try:
            with self._lock:
                self._stats['streams_opened'] += 1
            
            response = session.get(url, stream=True, timeout=timeout)
            
            # Track active stream
            with self._lock:
                self._active_streams[stream_id] = {
                    'response': response,
                    'url': url,
                    'start_time': time.time()
                }
            
            logger.debug(f"[SocketManager] Stream {stream_id} opened for {url}")
            
            # Yield chunks
            for chunk in response.iter_content(chunk_size=chunk_size):
                yield chunk
                
        except Exception as e:
            with self._lock:
                self._stats['errors'] += 1
            logger.error(f"[SocketManager] Error in stream {stream_id}: {e}")
            raise
            
        finally:
            # Cleanup
            self._close_stream(stream_id, response)
    
    def _close_stream(self, stream_id: str, response: Optional[requests.Response] = None):
        """
        Close a stream and clean up resources.
        
        Args:
            stream_id: ID of the stream to close
            response: Optional response object to close
        """
        try:
            # Remove from tracking
            with self._lock:
                stream_info = self._active_streams.pop(stream_id, None)
                if stream_info and response is None:
                    response = stream_info.get('response')
            
            # Close response
            if response:
                try:
                    response.close()
                    if hasattr(response, 'raw'):
                        response.raw.close()
                        # Force close underlying socket
                        if hasattr(response.raw, '_fp'):
                            try:
                                response.raw._fp.close()
                            except:
                                pass
                except Exception as e:
                    logger.debug(f"[SocketManager] Error closing stream {stream_id}: {e}")
            
            with self._lock:
                self._stats['connections_closed'] += 1
            
            logger.debug(f"[SocketManager] Stream {stream_id} closed")
            
        except Exception as e:
            logger.error(f"[SocketManager] Error in _close_stream {stream_id}: {e}")
    
    def close_stream(self, stream_id: str) -> bool:
        """
        Manually close a stream by ID.
        This will interrupt any blocking iter_content() calls.
        
        Args:
            stream_id: ID of the stream to close
            
        Returns:
            bool: True if stream was found and closed
        """
        response = None
        with self._lock:
            if stream_id in self._active_streams:
                # Get response object while holding lock
                response = self._active_streams[stream_id].get('response')
            else:
                return False
        
        # Close response outside lock to avoid deadlock and interrupt blocking calls
        if response:
            try:
                # Force close the response to interrupt iter_content()
                response.close()
                if hasattr(response, 'raw'):
                    response.raw.close()
                    # Force close underlying socket to interrupt blocking reads
                    if hasattr(response.raw, '_fp') and response.raw._fp:
                        try:
                            response.raw._fp.close()
                        except:
                            pass
            except Exception as e:
                logger.debug(f"[SocketManager] Exception while force-closing stream {stream_id}: {e}")
        
        # Now clean up the tracking
        with self._lock:
            self._active_streams.pop(stream_id, None)
            self._stats['connections_closed'] += 1
        
        logger.debug(f"[SocketManager] Stream {stream_id} forcefully closed")
        return True
    
    def get_stream_generator(
        self,
        url: str,
        timeout: Optional[tuple] = None,
        chunk_size: int = 1024
    ) -> Generator[bytes, None, None]:
        """
        Create a simple streaming generator with automatic cleanup.
        Use this for one-off streams that don't need tracking.
        
        Args:
            url: URL to stream from
            timeout: Optional (connect, read) timeout tuple
            chunk_size: Size of chunks to yield
            
        Yields:
            bytes: Chunks of data from the stream
        """
        session = self._get_session(url)
        
        if timeout is None:
            timeout = self.stream_timeout
        
        response = None
        try:
            response = session.get(url, stream=True, timeout=timeout)
            
            for chunk in response.iter_content(chunk_size=chunk_size):
                yield chunk
                
        except Exception as e:
            logger.error(f"[SocketManager] Error in stream generator for {url}: {e}")
            raise
            
        finally:
            if response:
                try:
                    response.close()
                    if hasattr(response, 'raw'):
                        response.raw.close()
                except:
                    pass
    
    def close_all_streams(self):
        """Close all active streams."""
        stream_ids = []
        with self._lock:
            stream_ids = list(self._active_streams.keys())
        
        logger.info(f"[SocketManager] Closing {len(stream_ids)} active streams...")
        
        for stream_id in stream_ids:
            self._close_stream(stream_id)
        
        logger.info("[SocketManager] All streams closed")
    
    def close_all_sessions(self):
        """Close all session connections."""
        with self._lock:
            session_count = len(self._sessions)
            
            for host, session in self._sessions.items():
                try:
                    session.close()
                    logger.debug(f"[SocketManager] Closed session for {host}")
                except Exception as e:
                    logger.error(f"[SocketManager] Error closing session for {host}: {e}")
            
            self._sessions.clear()
            logger.info(f"[SocketManager] Closed {session_count} sessions")
    
    def shutdown(self):
        """Shutdown the socket manager and clean up all resources."""
        logger.info("[SocketManager] Shutting down...")
        
        # Close all streams first
        self.close_all_streams()
        
        # Then close all sessions
        self.close_all_sessions()
        
        logger.info("[SocketManager] Shutdown complete")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about socket usage.
        
        Returns:
            dict: Statistics dictionary
        """
        with self._lock:
            return {
                **self._stats,
                'active_streams': len(self._active_streams),
                'active_sessions': len(self._sessions)
            }
    
    def get_active_streams(self) -> Dict[str, Dict[str, Any]]:
        """
        Get information about active streams.
        
        Returns:
            dict: Dictionary of stream_id -> stream_info
        """
        with self._lock:
            return {
                stream_id: {
                    'url': info['url'],
                    'duration': time.time() - info['start_time']
                }
                for stream_id, info in self._active_streams.items()
            }
    
    def cleanup_old_streams(self, max_age_seconds: float = 3600):
        """
        Close streams that have been open for too long.
        
        Args:
            max_age_seconds: Maximum age in seconds before closing
        """
        current_time = time.time()
        to_close = []
        
        with self._lock:
            for stream_id, info in self._active_streams.items():
                age = current_time - info['start_time']
                if age > max_age_seconds:
                    to_close.append(stream_id)
        
        for stream_id in to_close:
            logger.warning(f"[SocketManager] Closing old stream {stream_id} (age: {age:.1f}s)")
            self._close_stream(stream_id)
        
        if to_close:
            logger.info(f"[SocketManager] Cleaned up {len(to_close)} old streams")


# Global singleton instance
_socket_manager_instance = None
_instance_lock = threading.Lock()


def get_socket_manager() -> SocketManager:
    """
    Get the global SocketManager singleton instance.
    
    Returns:
        SocketManager: The global socket manager instance
    """
    global _socket_manager_instance
    
    if _socket_manager_instance is None:
        with _instance_lock:
            if _socket_manager_instance is None:
                _socket_manager_instance = SocketManager()
    
    return _socket_manager_instance


def shutdown_socket_manager():
    """Shutdown the global socket manager."""
    global _socket_manager_instance
    
    if _socket_manager_instance is not None:
        _socket_manager_instance.shutdown()
