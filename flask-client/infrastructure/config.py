"""
Infrastructure Configuration

Centralized configuration for socket management, server connections,
timeouts, and other infrastructure-related settings.
"""

# ============================================================================
# Socket Manager Configuration
# ============================================================================

# Connection pool settings
SOCKET_MAX_CONNECTIONS_PER_HOST = 20  # Max connections per host
SOCKET_MAX_TOTAL_CONNECTIONS = 100    # Max total connections across all hosts

# Timeout settings (in seconds)
# Format: (connect_timeout, read_timeout)
SOCKET_DEFAULT_TIMEOUT = (5, 30)      # Default timeout for regular requests
SOCKET_STREAM_TIMEOUT = (10, 300)     # Timeout for long-running video streams (5 minutes read)

# Stream chunk size
SOCKET_STREAM_CHUNK_SIZE = 8192       # Default chunk size for streaming

# ============================================================================
# Server Configuration
# ============================================================================

# Server endpoints
WEBCAM_SERVER_URL = "http://localhost"
WEBCAM_SERVER_PORT = 5001
WEBCAM_SERVER_HEALTH_ENDPOINT = "/devices"
WEBCAM_VIDEO_ENDPOINT = "/video"

LEGACY_CAMERA_SERVER_URL = "http://localhost"
LEGACY_CAMERA_SERVER_PORT = 5002
LEGACY_CAMERA_SERVER_HEALTH_ENDPOINT = "/devices"
LEGACY_CAMERA_VIDEO_ENDPOINT = "/camera-video"  # Append /{device_id}

SIMULATOR_SERVER_URL = "http://localhost"
SIMULATOR_SERVER_PORT = 5003
SIMULATOR_SERVER_HEALTH_ENDPOINT = "/devices"
SIMULATOR_VIDEO_ENDPOINT = "/video/simulator"

# ============================================================================
# Health Monitoring Configuration
# ============================================================================

# Health check intervals (in seconds)
HEALTH_CHECK_INTERVAL = 10.0          # How often to check server health
HEALTH_CHECK_TIMEOUT = 1.5            # Timeout for health check requests

# ============================================================================
# Connected Devices Query Configuration
# ============================================================================

# Device query timeouts (in seconds)
# Format: (connect_timeout, read_timeout)
DEVICE_QUERY_TIMEOUT = (1, 2)         # Quick timeout for device queries
DEVICE_QUERY_MAX_WAIT = 5             # Max time to wait for all queries to complete

# ============================================================================
# Thread Start Validation Configuration
# ============================================================================

# Server availability check timeout before starting threads
THREAD_START_SERVER_CHECK_TIMEOUT = (1, 2)  # Quick check before starting processing

# ============================================================================
# Video Stream Processing Configuration
# ============================================================================

# Buffer settings
STREAM_MAX_BUFFER_SIZE = 10 * 1024 * 1024  # 10MB max buffer for video frames

# Frame processing
STREAM_CHUNK_CHECK_INTERVAL = 5       # Check stop flag every N chunks


# ============================================================================
# Helper Functions
# ============================================================================

def get_server_url(server_type: str) -> str:
    """
    Get the full base URL for a server type.
    
    Args:
        server_type: One of 'webcam', 'legacy', 'simulator'
        
    Returns:
        Full base URL (e.g., 'http://localhost:5001')
    """
    if server_type == 'webcam':
        return f"{WEBCAM_SERVER_URL}:{WEBCAM_SERVER_PORT}"
    elif server_type == 'legacy':
        return f"{LEGACY_CAMERA_SERVER_URL}:{LEGACY_CAMERA_SERVER_PORT}"
    elif server_type == 'simulator':
        return f"{SIMULATOR_SERVER_URL}:{SIMULATOR_SERVER_PORT}"
    else:
        raise ValueError(f"Unknown server type: {server_type}")


def get_server_health_url(server_type: str) -> str:
    """
    Get the health check URL for a server type.
    
    Args:
        server_type: One of 'webcam', 'legacy', 'simulator'
        
    Returns:
        Full health check URL
    """
    if server_type == 'webcam':
        return f"{get_server_url('webcam')}{WEBCAM_SERVER_HEALTH_ENDPOINT}"
    elif server_type == 'legacy':
        return f"{get_server_url('legacy')}{LEGACY_CAMERA_SERVER_HEALTH_ENDPOINT}"
    elif server_type == 'simulator':
        return f"{get_server_url('simulator')}{SIMULATOR_SERVER_HEALTH_ENDPOINT}"
    else:
        raise ValueError(f"Unknown server type: {server_type}")


def get_server_video_url(server_type: str, device_id: int = None) -> str:
    """
    Get the video stream URL for a server type.
    
    Args:
        server_type: One of 'webcam', 'legacy', 'simulator'
        device_id: Device ID (required for legacy cameras)
        
    Returns:
        Full video stream URL
    """
    if server_type == 'webcam':
        return f"{get_server_url('webcam')}{WEBCAM_VIDEO_ENDPOINT}"
    elif server_type == 'legacy':
        if device_id is None:
            raise ValueError("device_id is required for legacy cameras")
        return f"{get_server_url('legacy')}{LEGACY_CAMERA_VIDEO_ENDPOINT}/{device_id}"
    elif server_type == 'simulator':
        return f"{get_server_url('simulator')}{SIMULATOR_VIDEO_ENDPOINT}"
    else:
        raise ValueError(f"Unknown server type: {server_type}")
