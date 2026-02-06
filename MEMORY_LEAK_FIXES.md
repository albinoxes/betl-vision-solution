# Memory Leak Fixes and Performance Improvements

## Issues Found and Fixed

### 1. **Unbounded Buffer Growth** ❌ CRITICAL
**Location:** `process_video_stream()` and `process_video_stream_background()`

**Problem:**
```python
buffer = b''
for chunk in r.iter_content(chunk_size=8192):
    buffer += chunk  # Buffer grows indefinitely!
```

The buffer accumulates all incoming video data without any size limit. Over time (especially with high-resolution video), this can consume gigabytes of RAM.

**Fix:**
```python
buffer = b''
MAX_BUFFER_SIZE = 10 * 1024 * 1024  # 10MB limit
for chunk in r.iter_content(chunk_size=8192):
    buffer += chunk
    if len(buffer) > MAX_BUFFER_SIZE:
        buffer = buffer[-MAX_BUFFER_SIZE//2:]  # Keep last half
```

---

### 2. **Unclosed HTTP Connections** ❌ CRITICAL
**Location:** `generate_frames()` and streaming functions

**Problem:**
```python
def generate_frames():
    r = requests.get(CAMERA_URL, stream=True)  # Never closed!
    return Response(r.iter_content(chunk_size=1024), ...)
```

The HTTP connection remains open indefinitely, consuming file descriptors and memory. On Windows, this causes socket exhaustion.

**Fix:**
```python
def generate_frames():
    r = None
    try:
        r = requests.get(CAMERA_URL, stream=True, timeout=(5, None))
        for chunk in r.iter_content(chunk_size=1024):
            yield chunk
    finally:
        if r is not None:
            r.close()
            if hasattr(r, 'raw'):
                r.raw.close()
```

---

### 3. **Numpy Array Accumulation** ❌ MEDIUM
**Location:** Frame processing loops

**Problem:**
```python
nparr = np.frombuffer(jpeg_data, np.uint8)
img2d = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
# Process image...
# Arrays never explicitly deleted - rely on garbage collector
```

Large numpy arrays (video frames) are created continuously but not explicitly freed. Python's garbage collector may not run frequently enough, causing memory to accumulate.

**Fix:**
```python
nparr = np.frombuffer(jpeg_data, np.uint8)
img2d = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
# Process image...
# Explicitly delete to free memory immediately
del img2d
del nparr
```

---

### 4. **Session Dictionary Growing Unbounded** ❌ MEDIUM
**Location:** `StoreDataManager.active_sessions`

**Problem:**
```python
self.active_sessions = {}
# Sessions added but never removed for old/inactive threads
```

Every video thread creates a session entry that persists even after the thread stops. Over multiple runs, this dictionary grows indefinitely.

**Fix:**
```python
def cleanup_old_sessions(self):
    """Remove sessions older than 2x duration limit."""
    current_time = datetime.now()
    to_remove = []
    for session_key, session_info in self.active_sessions.items():
        elapsed = (current_time - session_info['folder_start_time']).total_seconds() / 60
        if elapsed > self.session_duration_minutes * 2:
            to_remove.append(session_key)
    for key in to_remove:
        del self.active_sessions[key]
```

---

### 5. **ML Models Not Being Freed** ⚠️ MEDIUM
**Location:** Thread cleanup in `process_video_stream_background()`

**Problem:**
ML models (PyTorch/TensorFlow) can consume hundreds of MB or even GBs of memory. Without explicit cleanup and garbage collection, they may persist in memory.

**Fix:**
```python
finally:
    if model is not None:
        try:
            del model
            del settings
        except:
            pass
    
    # Force garbage collection
    import gc
    gc.collect()
```

---

### 6. **No Garbage Collection Triggers** ⚠️ LOW-MEDIUM
**Problem:**
Python's garbage collector runs periodically, but with large objects (images, models) being created rapidly, manual triggering helps prevent accumulation.

**Fix:**
Added `gc.collect()` calls in cleanup sections of long-running processes.

---

## Additional Performance Improvements

### 1. **ThreadManager Integration**
Replaced manual thread tracking with centralized `ThreadManager`:
- Automatic cleanup of stopped threads
- Prevents thread object accumulation
- Proper lifecycle management

### 2. **Monitoring Endpoints**
Added endpoints to monitor and trigger cleanup:
- `GET /system-resources` - View memory, CPU, thread counts
- `POST /cleanup-resources` - Manually trigger cleanup

### 3. **Automatic Cleanup on Exit**
Added `@atexit.register` handler to stop all threads when app closes:
```python
@atexit.register
def cleanup_threads_on_exit():
    thread_manager.stop_all_threads(timeout=10.0)
```

---

## Recommendations for Further Optimization

### 1. **Implement Frame Rate Limiting**
Process frames at a fixed rate (e.g., 1 FPS) instead of processing every frame:
```python
if time.time() - last_process_time < 1.0:
    continue  # Skip this frame
```

### 2. **Use Shared Memory for Frames**
If multiple processes need the same frames, use `multiprocessing.shared_memory` instead of copying data.

### 3. **Implement Frame Queue with Max Size**
Use `queue.Queue(maxsize=10)` to limit buffered frames and apply backpressure.

### 4. **Monitor Disk Space**
Frames are being saved continuously. Add disk space monitoring:
```python
import shutil
disk_usage = shutil.disk_usage(storage_path)
if disk_usage.free < 1 * 1024**3:  # Less than 1GB free
    logger.warning("Low disk space!")
```

### 5. **Implement Log Rotation**
Logs can grow indefinitely. Use `RotatingFileHandler` or `TimedRotatingFileHandler`.

### 6. **Reduce Image Quality for Storage**
Save frames with lower JPEG quality to reduce disk I/O and storage:
```python
cv2.imwrite(filepath, image, [cv2.IMWRITE_JPEG_QUALITY, 70])
```

---

## Testing Memory Leaks

### Monitor Memory Usage
```python
# Add to camera_controller.py
import tracemalloc
tracemalloc.start()

# In cleanup:
snapshot = tracemalloc.take_snapshot()
top_stats = snapshot.statistics('lineno')
for stat in top_stats[:10]:
    print(stat)
```

### Use Memory Profiler
```bash
pip install memory_profiler
python -m memory_profiler app.py
```

### Monitor in Production
Use `GET /system-resources` endpoint to track:
- Memory growth over time
- Thread count increases
- Active session accumulation

---

## Summary

**Critical Fixes:**
✅ Added buffer size limits (10MB max)
✅ Proper HTTP connection cleanup with try/finally
✅ Explicit numpy array deletion
✅ Session cleanup mechanism
✅ ThreadManager for proper thread lifecycle

**Performance Improvements:**
✅ Garbage collection triggers in cleanup
✅ Manual cleanup endpoint
✅ Enhanced monitoring with session counts
✅ App shutdown cleanup handler

**Expected Impact:**
- Memory usage should stabilize after ~30 minutes
- No gradual memory growth on second/third runs
- Faster response times (less GC pressure)
- No socket exhaustion on Windows
