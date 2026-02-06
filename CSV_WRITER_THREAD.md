# CSV Writer Thread - Separation of Concerns

## Overview
CSV generation has been separated into its own dedicated thread, creating a clean three-stage pipeline with no direct coupling between stages:

```
Camera Thread → CSV Writer Thread → SFTP Uploader Thread
   (data)         (CSV files)          (uploads)
```

## Architecture

### Stage 1: Camera Processing Thread
**Responsibility**: Capture frames, run ML models, generate detection data

**Actions**:
- Processes video frames
- Runs object detection / classification
- **Queues CSV generation request** (non-blocking)
- Provides callback for when CSV is complete

**Does NOT**:
- Write CSV files directly
- Trigger SFTP uploads directly
- Block on I/O operations

### Stage 2: CSV Writer Thread
**Responsibility**: Write CSV files to disk (single responsibility)

**Actions**:
- Receives CSV generation requests via queue
- Writes CSV files using `iris_input_processor`
- Calls callback when CSV is complete
- Tracks statistics (queued, written, failed)

**Does NOT**:
- Know about SFTP uploads
- Trigger uploads directly
- Depend on SFTP thread

### Stage 3: SFTP Uploader Thread
**Responsibility**: Upload CSV files to SFTP server

**Actions**:
- Receives upload requests via queue
- Uploads CSV files to remote server
- Handles connection management
- Tracks upload statistics

**Does NOT**:
- Generate CSV files
- Know about camera processing
- Depend on CSV writer

## Communication Flow

### Model Detection Processing:
```
1. Camera Thread: Detects particles
2. Camera Thread: queue_csv_generation(data, callback=on_model_csv_complete)
   └─> Returns immediately (non-blocking)
3. CSV Writer Thread: Generates CSV file
4. CSV Writer Thread: Calls on_model_csv_complete(csv_path)
5. Callback: queue_upload(csv_path) → SFTP thread
6. SFTP Thread: Uploads CSV to server
```

### Classifier Processing:
```
1. Camera Thread: Classifies belt status
2. Camera Thread: queue_csv_generation(data, callback=on_classifier_csv_complete)
   └─> Returns immediately (non-blocking)
3. CSV Writer Thread: Generates CSV file
4. CSV Writer Thread: Calls on_classifier_csv_complete(csv_path)
5. Callback: queue_upload(csv_path) → SFTP thread
6. SFTP Thread: Uploads CSV to server
```

## Benefits of Separation

### 1. **No Direct Coupling**
- CSV writer doesn't know about SFTP
- SFTP uploader doesn't know about CSV generation
- Each thread has a single responsibility

### 2. **Independent Failure Domains**
- CSV generation failure doesn't crash camera thread
- SFTP upload failure doesn't affect CSV writing
- Each component can fail and recover independently

### 3. **Better Performance**
- Camera thread never blocks on file I/O
- CSV writing happens in parallel
- SFTP uploads don't slow down processing

### 4. **Cleaner Testing**
- Test CSV generation without SFTP
- Test SFTP uploads without CSV generation
- Mock each component independently

### 5. **Queue Buffering**
- CSV queue: 200 items (handles burst writes)
- SFTP queue: 100 items (handles slow network)
- Prevents data loss during temporary issues

## Code Changes

### New File: `csv_writer_thread.py`
- `CsvWriterThread` class
- Queue-based CSV generation
- Callback mechanism for completion notification
- Statistics tracking

### Updated: `camera_controller.py`
**Before**:
```python
csv_path = iris_input_processor.generate_iris_input_data(...)
if csv_path:
    sftp_uploader.queue_upload(csv_path, ...)
```

**After**:
```python
def on_csv_complete(csv_path):
    if previous_csv_path:
        sftp_uploader.queue_upload(previous_csv_path, ...)
    previous_csv_path = csv_path

csv_writer.queue_csv_generation(..., callback=on_csv_complete)
```

### Updated: `app.py`
- Start CSV writer thread on startup
- Stop CSV writer before SFTP uploader on shutdown
- Added to cleanup handlers

## Thread Lifecycle

### Startup Order:
1. Logger
2. **CSV Writer Thread** ← starts first
3. **SFTP Uploader Thread** ← starts second
4. Health Monitoring
5. Camera Threads (on demand)

### Shutdown Order:
1. Camera Threads (stop first)
2. **CSV Writer Thread** ← finish pending CSVs
3. **SFTP Uploader Thread** ← upload remaining CSVs
4. Socket Manager
5. Health Service
6. Logger

## Monitoring

### CSV Writer Stats:
```bash
curl http://localhost:5000/csv-writer-stats
```

Response:
```json
{
  "running": true,
  "stats": {
    "total_queued": 450,
    "total_written": 448,
    "total_failed": 2,
    "queue_size": 0
  }
}
```

### SFTP Uploader Stats:
```bash
curl http://localhost:5000/sftp-uploader-stats
```

Response:
```json
{
  "running": true,
  "stats": {
    "total_queued": 445,
    "total_uploaded": 440,
    "total_failed": 5,
    "queue_size": 3
  }
}
```

## Error Handling

### CSV Queue Full:
- Returns `False` from `queue_csv_generation()`
- Camera processing continues
- Warning logged
- Statistics not incremented

### CSV Generation Fails:
- Error logged with traceback
- Callback NOT called (no invalid upload triggered)
- `total_failed` incremented
- Next CSV generation proceeds normally

### SFTP Upload Fails:
- Error logged by SFTP thread
- CSV file remains on disk
- Does not affect CSV writer
- Does not affect camera processing

## Key Design Principles

1. **Single Responsibility**: Each thread does one thing
2. **Loose Coupling**: Threads communicate via callbacks, not direct calls
3. **Fail Independently**: Errors are isolated to one component
4. **Non-Blocking**: No thread waits for another to complete work
5. **Observable**: Each thread exposes statistics for monitoring

## Future Enhancements

1. **Retry Logic**: Failed CSV writes could be retried
2. **Disk Space Monitoring**: Pause CSV generation if disk full
3. **Rate Limiting**: Throttle CSV generation during high load
4. **Compression**: Compress CSV files before SFTP upload
5. **Batch CSV**: Combine multiple small CSVs into one file
