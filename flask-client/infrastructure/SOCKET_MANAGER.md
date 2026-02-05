# SocketManager Documentation

## Overview

The **SocketManager** provides centralized HTTP connection management for all inter-service communication in the Belt Vision Solution. It prevents socket leaks, manages connection pooling, and ensures proper resource cleanup.

## Architecture

```
┌─────────────────────────────────────────────┐
│          Flask Client App                    │
│  ┌────────────────────────────────────────┐ │
│  │        SocketManager (Singleton)       │ │
│  │  ┌──────────────────────────────────┐  │ │
│  │  │   Connection Pool per Host       │  │ │
│  │  │  ┌─────────────┬─────────────┐   │  │ │
│  │  │  │ Session #1  │ Session #2  │   │  │ │
│  │  │  │ (Port 5001) │ (Port 5002) │   │  │ │
│  │  │  └─────────────┴─────────────┘   │  │ │
│  │  └──────────────────────────────────┘  │ │
│  │  ┌──────────────────────────────────┐  │ │
│  │  │   Active Streams Tracking        │  │ │
│  │  │  stream_id -> response object    │  │ │
│  │  └──────────────────────────────────┘  │ │
│  └────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
         │          │          │
         ▼          ▼          ▼
    ┌────────┐ ┌────────┐ ┌────────┐
    │Webcam  │ │Legacy  │ │Simula- │
    │Server  │ │Camera  │ │tor     │
    │:5001   │ │:5002   │ │:5003   │
    └────────┘ └────────┘ └────────┘
```

## Features

### 1. Connection Pooling ✅
- Reuses HTTP connections per host
- Reduces connection overhead
- Configurable pool size
- Automatic connection management

### 2. Stream Management ✅
- Tracks all active streams by ID
- Automatic cleanup on completion
- Force-close capability
- Age-based cleanup for orphaned streams

### 3. Memory Leak Prevention ✅
- Proper socket closure at all layers
- Session cleanup on shutdown
- Stream tracking prevents orphaned connections
- Garbage collection friendly

### 4. Performance Optimization ✅
- Connection reuse reduces latency
- Thread-safe operations
- Minimal locking overhead
- Statistics tracking

## API Reference

### Basic Usage

```python
from infrastructure.socket_manager import get_socket_manager

# Get singleton instance
socket_manager = get_socket_manager()
```

### Making Simple Requests

```python
# GET request with automatic cleanup
response = socket_manager.get(
    'http://localhost:5001/devices',
    timeout=(5, 30)  # (connect_timeout, read_timeout)
)

# Response is a standard requests.Response object
if response.status_code == 200:
    data = response.json()
```

### Streaming Data

**Option 1: Simple Generator (Untracked)**
```python
# For one-off streams that don't need tracking
def my_video_feed():
    for chunk in socket_manager.get_stream_generator(
        'http://localhost:5001/video',
        chunk_size=1024
    ):
        yield chunk
        
return Response(my_video_feed(), mimetype='multipart/x-mixed-replace')
```

**Option 2: Tracked Stream**
```python
# For long-running streams that need management
stream_id = "camera_feed_1"

try:
    for chunk in socket_manager.stream(
        stream_id=stream_id,
        url='http://localhost:5001/video',
        chunk_size=8192
    ):
        # Process chunk
        process_frame(chunk)
        
        # Can check if stream should stop
        if should_stop:
            socket_manager.close_stream(stream_id)
            break
except Exception as e:
    logger.error(f"Stream error: {e}")
    socket_manager.close_stream(stream_id)
```

### Monitoring and Cleanup

```python
# Get statistics
stats = socket_manager.get_stats()
print(f"Requests made: {stats['requests_made']}")
print(f"Active streams: {stats['active_streams']}")
print(f"Errors: {stats['errors']}")

# Get active stream info
active_streams = socket_manager.get_active_streams()
for stream_id, info in active_streams.items():
    print(f"{stream_id}: {info['url']} (duration: {info['duration']:.1f}s)")

# Cleanup old streams (older than 1 hour)
socket_manager.cleanup_old_streams(max_age_seconds=3600)

# Close specific stream
socket_manager.close_stream("camera_feed_1")

# Close all streams
socket_manager.close_all_streams()

# Close all sessions
socket_manager.close_all_sessions()

# Full shutdown (typically on app exit)
socket_manager.shutdown()
```

## Configuration

Default configuration in SocketManager:

```python
socket_manager = SocketManager(
    max_connections_per_host=10,      # Max connections to each server
    max_total_connections=50,          # Total max connections
    default_timeout=(5, 30),           # Default (connect, read) timeout
    stream_timeout=(5, 10)             # Streaming timeout (faster failover)
)
```

## Integration Points

### 1. camera_controller.py

**Before (Memory Leaks):**
```python
r = requests.get(url, stream=True, timeout=(5, None))
for chunk in r.iter_content(chunk_size=8192):
    # Process chunk
    pass
# Connection never properly closed!
```

**After (Clean):**
```python
for chunk in socket_manager.stream(thread_id, url, chunk_size=8192):
    # Process chunk
    pass
# Automatically cleaned up
```

### 2. Application Shutdown

**app.py:**
```python
def cleanup_threads():
    # Stop threads first
    thread_manager.stop_all_threads(timeout=10.0)
    
    # Then close all sockets
    socket_manager.shutdown()
    
    # Other cleanup...
```

### 3. Monitoring Endpoint

```python
@app.route('/system-resources')
def get_system_resources():
    socket_stats = socket_manager.get_stats()
    
    return jsonify({
        'memory_mb': ...,
        'active_threads': ...,
        'socket_manager': socket_stats  # Detailed socket info
    })
```

## Benefits

### Memory Leak Prevention
- ✅ No orphaned sockets
- ✅ Proper multi-layer cleanup (response → raw → socket)
- ✅ Session pooling prevents connection accumulation
- ✅ Automatic cleanup on errors

### Performance Improvements
- ⚡ Connection reuse reduces overhead
- ⚡ Thread-safe connection pooling
- ⚡ Configurable timeouts prevent hanging
- ⚡ Statistics for performance monitoring

### Maintainability
- 📝 Centralized connection logic
- 📝 Consistent error handling
- 📝 Easy to debug (tracking and stats)
- 📝 Clean API surface

## Statistics Tracking

SocketManager tracks:

```python
stats = socket_manager.get_stats()
# Returns:
{
    'requests_made': 1523,      # Total GET requests
    'streams_opened': 12,        # Total streams created
    'connections_closed': 1520,  # Total cleanups
    'errors': 3,                 # Total errors
    'active_streams': 2,         # Currently active
    'active_sessions': 3         # Currently open sessions
}
```

## Error Handling

SocketManager handles errors gracefully:

```python
try:
    response = socket_manager.get(url)
except requests.exceptions.Timeout:
    # Connection or read timeout
    logger.error("Request timed out")
except requests.exceptions.ConnectionError:
    # Server unreachable
    logger.error("Cannot connect to server")
except Exception as e:
    # Other errors
    logger.error(f"Request failed: {e}")
```

All errors are logged and counted in statistics.

## Best Practices

### 1. Always Use SocketManager
❌ **Don't:**
```python
r = requests.get(url)  # Direct requests usage
```

✅ **Do:**
```python
response = socket_manager.get(url)  # Managed connection
```

### 2. Use Appropriate Timeouts
```python
# Short-lived request
response = socket_manager.get(url, timeout=(2, 5))

# Long-running stream
for chunk in socket_manager.stream(id, url, timeout=(5, 10)):
    pass
```

### 3. Close Long-Running Streams
```python
stream_id = f"thread_{thread_id}"

try:
    for chunk in socket_manager.stream(stream_id, url):
        if stop_condition:
            socket_manager.close_stream(stream_id)
            break
finally:
    # Ensure cleanup
    socket_manager.close_stream(stream_id)
```

### 4. Monitor Statistics
```python
# Periodically check stats
stats = socket_manager.get_stats()

if stats['active_streams'] > 50:
    logger.warning("Too many active streams!")
    
if stats['errors'] > stats['requests_made'] * 0.1:
    logger.warning("High error rate!")
```

### 5. Clean Up Old Resources
```python
# In periodic cleanup task
socket_manager.cleanup_old_streams(max_age_seconds=1800)  # 30 min
thread_manager.cleanup_stopped_threads(max_age=60)
store_data_manager.cleanup_old_sessions()
```

## Troubleshooting

### Problem: "Too many open files"
**Cause:** Socket leaks
**Solution:** SocketManager prevents this by:
- Automatic cleanup of all streams
- Connection pooling
- Age-based cleanup

### Problem: Slow performance after running for hours
**Cause:** Connection accumulation
**Solution:** 
```python
# Manually trigger cleanup
socket_manager.cleanup_old_streams()
socket_manager.close_all_sessions()  # Recreates fresh sessions
```

### Problem: Hanging on Ctrl+C
**Cause:** Blocking socket reads
**Solution:** SocketManager uses read timeouts:
```python
stream_timeout=(5, 10)  # 10 second read timeout
```

## Testing

### Manual Testing
```python
# Test connection pooling
for i in range(100):
    response = socket_manager.get('http://localhost:5001/devices')
    print(f"Request {i}: {response.status_code}")

stats = socket_manager.get_stats()
print(f"Sessions created: {stats['active_sessions']}")  # Should be 1
```

### Load Testing
```python
import threading

def make_requests():
    for i in range(100):
        socket_manager.get('http://localhost:5001/devices')

threads = [threading.Thread(target=make_requests) for _ in range(10)]
for t in threads:
    t.start()
for t in threads:
    t.join()

print(socket_manager.get_stats())
```

## Summary

The SocketManager is a critical component that:

1. ✅ Prevents socket/memory leaks
2. ✅ Improves performance through connection pooling  
3. ✅ Provides centralized monitoring
4. ✅ Ensures clean shutdown
5. ✅ Simplifies error handling

**Always use SocketManager instead of direct `requests` calls!**
