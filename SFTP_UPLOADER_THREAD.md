# SFTP Uploader Thread Implementation

## Overview
The SFTP uploader has been separated into its own dedicated thread with a single responsibility: handling SFTP file uploads asynchronously. This implementation ensures that SFTP operations don't block the main camera processing thread and that the thread is properly cleaned up when the application exits.

## Changes Made

### 1. New File: `iris_communication/sftp_uploader_thread.py`
Created a dedicated SFTP uploader thread module with the following features:

#### Key Components:
- **SftpUploadRequest**: Data class representing a single upload request
- **SftpUploaderThread**: Main class managing the upload queue and worker thread
- **get_sftp_uploader()**: Singleton factory function

#### Features:
- **Queue-based System**: Uses `queue.Queue` (max 100 items) for thread-safe upload requests
- **Single Responsibility**: Only handles SFTP uploads, nothing else
- **Graceful Shutdown**: 
  - Responds to stop signals immediately
  - Processes remaining queue items before exiting
  - Configurable timeout (default 10s, with 15s in app cleanup)
- **Statistics Tracking**: Monitors total queued, uploaded, failed, and current queue size
- **Error Handling**: Catches and logs errors without crashing the thread
- **Non-blocking**: Upload requests use `put_nowait()` to avoid blocking the caller

### 2. Updated: `controllers/camera_controller.py`
Modified to use the SFTP uploader thread instead of direct SFTP calls:

#### Changes:
- **Import**: Added `from iris_communication.sftp_uploader_thread import get_sftp_uploader`
- **Initialization**: Created global `sftp_uploader` instance
- **Model CSV Upload** (line ~247): Replaced direct `sftp_processor.transferData()` with `sftp_uploader.queue_upload()`
- **Classifier CSV Upload** (line ~293): Replaced direct `sftp_processor.transferData()` with `sftp_uploader.queue_upload()`
- **New Endpoint**: Added `/sftp-uploader-stats` to monitor the uploader thread

#### Benefits:
- Camera processing no longer blocks on SFTP uploads
- SFTP failures don't impact frame processing
- Upload queue provides buffering during network issues

### 3. Updated: `app.py`
Modified to start and stop the SFTP uploader thread during application lifecycle:

#### Changes:
- **Import**: Added `from iris_communication.sftp_uploader_thread import get_sftp_uploader`
- **Startup**: Starts SFTP uploader thread immediately after logging initialization
- **Shutdown**: Stops SFTP uploader in two places:
  1. `cleanup_threads()`: Stops with 15s timeout to process remaining uploads
  2. `cleanup_on_exit()`: Emergency stop with 5s timeout

#### Shutdown Order:
1. SFTP uploader (processes remaining uploads)
2. Camera processing threads
3. Socket manager
4. Health service
5. Logger

## Thread Lifecycle

### Startup:
```python
# In app.py
sftp_uploader = get_sftp_uploader()
sftp_uploader.start()  # Creates daemon thread running _upload_worker()
```

### Runtime:
```python
# In camera_controller.py
sftp_uploader.queue_upload(
    sftp_server_info=sftp_server_info,
    file_path=previous_model_csv_path,
    project_settings=project_settings,
    folder_type='model'
)
# Returns immediately, upload happens in background
```

### Shutdown:
```python
# In app.py cleanup_threads()
sftp_uploader.stop(timeout=15.0)
# 1. Sets stop event
# 2. Waits for current upload to finish
# 3. Processes remaining queue items
# 4. Thread exits gracefully
```

## Architecture

### Thread Communication:
```
Camera Thread                SFTP Uploader Thread
     |                              |
     | queue_upload()               |
     |----------------------------->|
     | (returns immediately)        |
     |                              |
     |                         [Queue: FIFO]
     |                              |
     |                         _upload_worker()
     |                              |
     |                         sftp_processor.transferData()
     |                              |
```

### Queue Behavior:
- **Max Size**: 100 items
- **Block on Full**: No, returns False if full
- **Process Order**: FIFO (First In, First Out)
- **Shutdown**: Processes remaining items before exit

## Benefits

1. **Separation of Concerns**: SFTP logic isolated from camera processing
2. **Non-blocking**: Camera thread doesn't wait for slow network operations
3. **Resilient**: Network errors don't crash camera processing
4. **Graceful Shutdown**: Ensures pending uploads complete before exit
5. **Observable**: Statistics endpoint shows queue health
6. **Resource Efficient**: Single thread handles all SFTP operations

## Monitoring

### Check SFTP Uploader Status:
```bash
curl http://localhost:5000/sftp-uploader-stats
```

### Response:
```json
{
  "running": true,
  "stats": {
    "total_queued": 150,
    "total_uploaded": 145,
    "total_failed": 2,
    "queue_size": 3
  }
}
```

## Error Handling

### Queue Full:
- Upload request returns `False`
- Warning logged: "Upload queue is full, dropping request"
- Camera processing continues unaffected

### Upload Failed:
- Error logged with details
- Statistics incremented (`total_failed`)
- Next upload proceeds normally

### Thread Crash:
- Thread wrapper catches exceptions
- Error logged with traceback
- Statistics show in failed state

## Testing Recommendations

1. **Start Application**: Verify SFTP thread starts with app
2. **Process Frames**: Confirm uploads are queued, not blocking
3. **Monitor Stats**: Check `/sftp-uploader-stats` endpoint
4. **Shutdown**: Verify graceful shutdown with Ctrl+C
5. **Queue Stress**: Test behavior with 100+ uploads
6. **Network Failure**: Verify camera processing continues during SFTP errors

## Future Enhancements

1. **Retry Logic**: Add configurable retry attempts for failed uploads
2. **Persistent Queue**: Save queue to disk for recovery after crashes
3. **Priority Queue**: Upload critical files before others
4. **Batch Uploads**: Combine multiple small files into archives
5. **Health Checks**: Periodic SFTP server availability checks
