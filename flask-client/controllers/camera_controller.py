from flask import Blueprint, render_template, Response, jsonify, request, redirect, url_for
import requests
import cv2
import numpy as np
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from computer_vision.ml_model_image_processor import object_process_image, CameraSettings
from computer_vision.classifier_image_processor import classifier_process_image
from computer_vision.classifier_processor_thread import get_classifier_processor
from computer_vision.model_detector_thread import get_model_detector
from storage_data.store_data_manager import store_data_manager
from sqlite.video_stream_sqlite_provider import video_stream_provider
from iris_communication.iris_input_processor import iris_input_processor
from iris_communication.sftp_processor import sftp_processor
from iris_communication.sftp_uploader_thread import get_sftp_uploader
from iris_communication.csv_writer_thread import get_csv_writer
from sqlite.sftp_sqlite_provider import sftp_provider
from infrastructure.logging.logging_provider import get_logger
from infrastructure.thread_manager import get_thread_manager
from infrastructure.socket_manager import get_socket_manager
from infrastructure import config
import atexit

# Create Blueprint FIRST (must be before route decorators)
camera_bp = Blueprint('camera', __name__)

# Initialize logger, thread manager, socket manager, CSV writer, SFTP uploader, classifier processor, and model detector
logger = get_logger()
thread_manager = get_thread_manager()
socket_manager = get_socket_manager()
csv_writer = get_csv_writer()
sftp_uploader = get_sftp_uploader()
classifier_processor = get_classifier_processor()
model_detector = get_model_detector()

# Webcam server URL from config
CAMERA_URL = config.get_server_video_url('webcam')

# Processing interval in seconds - controls how often frames are processed with ML models
PROCESSING_INTERVAL_SECONDS = 1.0  # Process every 1 second

def generate_frames():
    """Generator with proper cleanup to prevent memory leaks."""
    # Use SocketManager for automatic cleanup
    for chunk in socket_manager.get_stream_generator(CAMERA_URL, chunk_size=1024):
        yield chunk

def create_model_csv_callback(sftp_server_info, project_settings, previous_csv_tracker):
    """
    Create a callback function for handling model CSV completion and SFTP upload.
    
    Args:
        sftp_server_info: SFTP server configuration
        project_settings: Project settings for SFTP paths
        previous_csv_tracker: Dict with 'path' key to track previous CSV path
        
    Returns:
        Callback function that handles CSV completion
    """
    def on_model_csv_complete(csv_path: str):
        # If there's a previous CSV, queue it for SFTP upload
        if previous_csv_tracker['path'] and sftp_server_info:
            logger.debug(f"[SFTP] Queuing model CSV for upload: {previous_csv_tracker['path']}")
            success = sftp_uploader.queue_upload(
                sftp_server_info=sftp_server_info,
                file_path=previous_csv_tracker['path'],
                project_settings=project_settings,
                folder_type='model'
            )
            if not success:
                logger.warning(f"[SFTP] Failed to queue model CSV upload (queue may be full)")
        # Update to current CSV path
        previous_csv_tracker['path'] = csv_path
    
    return on_model_csv_complete

def create_classifier_csv_callback(sftp_server_info, project_settings, previous_csv_tracker):
    """
    Create a callback function for handling classifier CSV completion and SFTP upload.
    
    Args:
        sftp_server_info: SFTP server configuration
        project_settings: Project settings for SFTP paths
        previous_csv_tracker: Dict with 'path' key to track previous CSV path
        
    Returns:
        Callback function that handles CSV completion
    """
    def on_classifier_csv_complete(csv_path: str):
        # If there's a previous CSV, queue it for SFTP upload
        if previous_csv_tracker['path'] and sftp_server_info:
            logger.debug(f"[SFTP] Queuing classifier CSV for upload: {previous_csv_tracker['path']}")
            success = sftp_uploader.queue_upload(
                sftp_server_info=sftp_server_info,
                file_path=previous_csv_tracker['path'],
                project_settings=project_settings,
                folder_type='classifier'
            )
            if not success:
                logger.warning(f"[SFTP] Failed to queue classifier CSV upload (queue may be full)")
        # Update to current CSV path
        previous_csv_tracker['path'] = csv_path
    
    return on_classifier_csv_complete

def _initialize_processing_context(thread_id, model_id, classifier_id, settings_id):
    """
    Initialize processing context including models, settings, and project configuration.
    
    Args:
        thread_id: Unique identifier for this thread
        model_id: Optional model identifier (name:version)
        classifier_id: Optional classifier identifier (name:version)
        settings_id: Optional settings identifier (name)
        
    Returns:
        Tuple of (settings_id, project_settings, project_title, processing_interval, sftp_server_info)
    """
    from sqlite.detection_model_settings_sqlite_provider import detection_model_settings_provider
    from sqlite.project_settings_sqlite_provider import project_settings_provider
    
    # Load camera settings
    if not settings_id:
        all_settings = detection_model_settings_provider.list_settings()
        if all_settings and len(all_settings) > 0:
            settings_id = all_settings[0][1]
            logger.info(f"[Thread {thread_id}] No settings specified, using first available: {settings_id}")
        else:
            logger.warning(f"[Thread {thread_id}] Warning: No camera settings found in database")
    
    # Get project settings
    project_settings = project_settings_provider.get_project_settings()
    project_title = project_settings.title if project_settings else "default"
    
    # Log IRIS configuration
    if project_settings:
        logger.info(f"[IRIS] Project settings loaded: {project_title}")
        logger.info(f"[IRIS] Main folder: {project_settings.iris_main_folder}")
        logger.info(f"[IRIS] Model subfolder: {project_settings.iris_model_subfolder}")
        logger.info(f"[IRIS] Classifier subfolder: {project_settings.iris_classifier_subfolder}")
        logger.info(f"[IRIS] Image processing interval: {project_settings.image_processing_interval}s")
        processing_interval = project_settings.image_processing_interval
    else:
        logger.warning(f"[IRIS] Warning: No project settings found!")
        processing_interval = PROCESSING_INTERVAL_SECONDS
    
    # Get SFTP server info
    sftp_server_info = None
    try:
        all_sftp_servers = sftp_provider.get_all_servers()
        if all_sftp_servers and len(all_sftp_servers) > 0:
            sftp_server_info = all_sftp_servers[0]
            logger.info(f"[SFTP] Using SFTP server: {sftp_server_info.server_name}")
        else:
            logger.info(f"[SFTP] No SFTP server configured. Files will not be uploaded.")
    except Exception as e:
        logger.error(f"[SFTP] Error loading SFTP server info: {e}")
    
    return settings_id, project_settings, project_title, processing_interval, sftp_server_info

def _load_model_and_settings(model_id, settings_id, thread_id):
    """
    Lazy-load ML model and camera settings.
    
    Args:
        model_id: Model identifier (name:version)
        settings_id: Settings identifier (name)
        thread_id: Thread identifier for logging
        
    Returns:
        Tuple of (model, settings, model_loaded)
    """
    from computer_vision.ml_model_image_processor import get_model_from_database, get_camera_settings
    
    try:
        logger.info(f"[Model] Lazy-loading model: {model_id}, settings: {settings_id}")
        model = get_model_from_database(model_id)
        settings = get_camera_settings(settings_id)
        logger.info(f"[Model] Model loaded successfully: {model}")
        logger.info(f"[Model] Settings loaded: {settings}")
        return model, settings, True
    except Exception as e:
        logger.error(f"[Model] Error loading model or settings: {e}")
        import traceback
        traceback.print_exc()
        return None, None, False

def _extract_jpeg_from_frame(frame_data):
    """
    Extract JPEG image data from MJPEG frame.
    
    Args:
        frame_data: Raw frame data from MJPEG stream
        
    Returns:
        Numpy array of decoded image, or None if extraction failed
    """
    header_end = frame_data.find(b'\r\n\r\n')
    if header_end == -1:
        return None
    
    jpeg_start = header_end + 4
    jpeg_end = frame_data.find(b'\r\n', jpeg_start)
    if jpeg_end == -1:
        jpeg_data = frame_data[jpeg_start:]
    else:
        jpeg_data = frame_data[jpeg_start:jpeg_end]
    
    # Decode JPEG to numpy array
    nparr = np.frombuffer(jpeg_data, np.uint8)
    img2d = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    # Clean up temporary array
    del nparr
    
    return img2d

def _save_frame_to_storage(img2d, thread_id, project_title, timestamp, filename):
    """
    Save frame to disk and database.
    
    Args:
        img2d: Frame image as numpy array
        thread_id: Thread identifier
        project_title: Project title for camera ID
        timestamp: Frame timestamp
        filename: Frame filename
        
    Returns:
        True if save was successful, False otherwise
    """
    try:
        # Save the frame to disk with session tracking
        filepath = store_data_manager.save_frame(img2d, session_key=thread_id, filename=filename)
        
        if filepath:
            # Insert frame record into database with project_id_camera_id format
            try:
                full_camera_id = f"{project_title}_{thread_id}"
                video_stream_provider.insert_segment(
                    camera_id=full_camera_id,
                    start_time=timestamp,
                    file_path=filepath
                )
                return True
            except Exception as e:
                logger.error(f"Error inserting frame record to database: {e}")
                return False
        return False
    except Exception as e:
        logger.error(f"Error saving frame: {e}")
        return False

def _queue_model_detection(img2d, model, settings, model_id, filename, processing_timestamp, 
                          project_settings, sftp_server_info):
    """
    Queue frame for model detection processing.
    
    Args:
        img2d: Frame image as numpy array
        model: ML model object
        settings: Camera settings object
        model_id: Model identifier
        filename: Frame filename
        processing_timestamp: Processing timestamp
        project_settings: Project settings
        sftp_server_info: SFTP server configuration
        
    Returns:
        True if queuing was successful, False otherwise
    """
    try:
        model_detector.queue_detection(
            frame=img2d,
            model=model,
            settings=settings,
            model_id=model_id,
            timestamp=processing_timestamp,
            image_filename=filename,
            project_settings=project_settings,
            sftp_server_info=sftp_server_info
        )
        return True
    except Exception as e:
        logger.error(f"Error queuing model detection: {e}")
        return False

def _queue_classifier_processing(img2d, classifier_id, processing_timestamp, 
                                project_settings, sftp_server_info):
    """
    Queue frame for classifier processing.
    
    Args:
        img2d: Frame image as numpy array
        classifier_id: Classifier identifier
        processing_timestamp: Processing timestamp
        project_settings: Project settings
        sftp_server_info: SFTP server configuration
        
    Returns:
        True if queuing was successful, False otherwise
    """
    try:
        classifier_processor.queue_classification(
            frame=img2d,
            classifier_id=classifier_id,
            timestamp=processing_timestamp,
            project_settings=project_settings,
            sftp_server_info=sftp_server_info
        )
        return True
    except Exception as e:
        logger.error(f"Error queuing classifier: {e}")
        return False

def _cleanup_processing_resources(thread_id, model, settings):
    """
    Clean up processing resources and free memory.
    
    Args:
        thread_id: Thread identifier
        model: ML model object to clean up
        settings: Settings object to clean up
    """
    logger.info(f"[Cleanup] Stopping thread {thread_id}")
    
    # Explicitly delete model to free memory
    if model is not None:
        try:
            del model
            del settings
            logger.info(f"[Cleanup] ML model unloaded from memory")
        except:
            pass
    
    # Clean up session tracking
    try:
        store_data_manager.end_session(thread_id)
    except Exception as e:
        logger.error(f"Error ending session: {e}")
    
    # Force garbage collection to free memory immediately
    import gc
    gc.collect()
    logger.info(f"[Cleanup] Memory freed via garbage collection")
    
    # Ensure stream is closed (SocketManager handles cleanup)
    socket_manager.close_stream(thread_id)
    logger.info(f"[Cleanup] Stream closed via SocketManager")

def process_video_stream_background(thread_id, url, model_id=None, classifier_id=None, settings_id=None):
    """
    Process video stream in background thread with DATA COLLECTION.
    
    This function handles background processing with CSV generation and SFTP uploads.
    It queues frames for ML processing via worker threads and saves results to CSV files.
    
    For real-time visualization only (no CSV/SFTP), use process_video_stream() instead.
    
    Args:
        thread_id: Unique identifier for this thread
        url: URL of the video stream
        model_id: Optional model identifier (name:version)
        classifier_id: Optional classifier identifier (name:version)
        settings_id: Optional settings identifier (name)
    """
    # Initialize processing context
    settings_id, project_settings, project_title, processing_interval, sftp_server_info = \
        _initialize_processing_context(thread_id, model_id, classifier_id, settings_id)
    
    # Lazy-load models only when needed (not at thread start)
    model = None
    settings = None
    model_loaded = False
    
    # Initialize timing trackers
    frame_count = 0
    last_model_processing_time = 0
    last_classifier_processing_time = 0
    last_frame_save_time = 0
    
    # Update thread status to running
    thread_manager.set_status(thread_id, 'running')
    thread_manager.update_metadata(thread_id, {'frame_count': 0})
    
    logger.info(f"[Thread {thread_id}] Starting stream processing")
    logger.info(f"[Thread {thread_id}] URL: {url}")
    logger.info(f"[Thread {thread_id}] Model ID: {model_id}, Classifier ID: {classifier_id}, Settings ID: {settings_id}")
    
    try:
        while True:
            # Check if thread should stop
            if not thread_manager.is_running(thread_id):
                logger.info(f"[Thread {thread_id}] Stop signal received, exiting")
                break
            
            try:
                # Use SocketManager for managed streaming
                logger.info(f"[Thread {thread_id}] Connecting to video stream: {url}")
                boundary = b'--frame'
                buffer = b''
                MAX_BUFFER_SIZE = config.STREAM_MAX_BUFFER_SIZE
                
                # Process chunks with periodic stop checks using SocketManager
                chunk_count = 0
                stream_started = False
                for chunk in socket_manager.stream(thread_id, url, chunk_size=config.SOCKET_STREAM_CHUNK_SIZE):
                    if not stream_started:
                        logger.info(f"[Thread {thread_id}] Connected successfully, receiving frames")
                        stream_started = True
                    chunk_count += 1
                    
                    # Check stop flag every N chunks for faster response on shutdown
                    if chunk_count % config.STREAM_CHUNK_CHECK_INTERVAL == 0:
                        if not thread_manager.is_running(thread_id):
                            logger.info(f"[Thread {thread_id}] Stop detected in chunk loop, exiting")
                            break
                    
                    buffer += chunk
                    
                    # Prevent buffer from growing unbounded
                    if len(buffer) > MAX_BUFFER_SIZE:
                        logger.warning(f"[Thread {thread_id}] Buffer exceeded {MAX_BUFFER_SIZE} bytes, truncating")
                        buffer = buffer[-MAX_BUFFER_SIZE//2:]
                    
                    while boundary in buffer:
                        start = buffer.find(boundary)
                        end = buffer.find(boundary, start + 1)
                        if end == -1:
                            break
                        
                        frame_data = buffer[start:end]
                        buffer = buffer[end:]
                        
                        # Extract JPEG image from frame
                        img2d = _extract_jpeg_from_frame(frame_data)
                        
                        if img2d is not None:
                            # Generate timestamp and filename for this frame
                            timestamp = datetime.now()
                            filename = f"frame_{timestamp.strftime('%Y%m%d_%H%M%S_%f')}.jpg"
                            
                            # Save frame to storage directory and database at the same interval as processing
                            current_time = time.time()
                            if current_time - last_frame_save_time >= processing_interval:
                                _save_frame_to_storage(img2d, thread_id, project_title, timestamp, filename)
                                last_frame_save_time = current_time
                            
                            # Lazy-load model only when we need to process
                            if model_id and not model_loaded:
                                model, settings, model_loaded = _load_model_and_settings(model_id, settings_id, thread_id)
                            elif not model_id:
                                logger.debug(f"[Model] No model_id provided, skipping model processing")
                                
                            # Process with ML models if specified
                            if model is not None:
                                current_time = time.time()
                                if current_time - last_model_processing_time >= processing_interval:
                                    logger.debug(f"[Processing] Queuing frame for model detection at {current_time:.2f}, interval: {current_time - last_model_processing_time:.2f}s")
                                    frame_count += 1
                                    processing_timestamp = datetime.now()
                                    
                                    _queue_model_detection(
                                        img2d, model, settings, model_id, filename,
                                        processing_timestamp, project_settings, sftp_server_info
                                    )
                                    
                                    last_model_processing_time = current_time
                            
                            if classifier_id:
                                current_time = time.time()
                                if current_time - last_classifier_processing_time >= processing_interval:
                                    logger.debug(f"[Processing] Queuing frame for classifier at {current_time:.2f}, interval: {current_time - last_classifier_processing_time:.2f}s")
                                    # Increment frame count (if not already incremented by model)
                                    if not model_id:
                                        frame_count += 1
                                    processing_timestamp = datetime.now()
                                    
                                    _queue_classifier_processing(
                                        img2d, classifier_id, processing_timestamp,
                                        project_settings, sftp_server_info
                                    )
                                    
                                    last_classifier_processing_time = current_time
                                
                            # Update frame count metadata
                            thread_manager.update_metadata(thread_id, {
                                'frame_count': frame_count,
                                'last_update': time.time()
                            })
                            
                            # Explicitly delete numpy array to free memory
                            del img2d
                
                # Stream is automatically closed by SocketManager
                # If we got here without errors, break the retry loop
                # to avoid unnecessary reconnections
                break
                
            except requests.exceptions.Timeout as e:
                # Timeout can occur during normal shutdown - check if stopping
                if not thread_manager.is_running(thread_id):
                    logger.info(f"[Thread {thread_id}] Timeout during shutdown (expected)")
                else:
                    logger.error(f"[Error] Timeout in thread {thread_id}: {e}")
                    logger.error(f"[Error] URL: {url}, Timeout details: {e}")
                    import traceback
                    logger.error(f"[Error] Stack trace: {traceback.format_exc()}")
                    thread_manager.set_status(thread_id, 'error: timeout')
                break
                
            except requests.exceptions.ConnectionError as e:
                # Connection error - server might be down
                logger.error(f"[Error] Connection error in thread {thread_id}: {e}")
                logger.error(f"[Error] URL: {url}")
                import traceback
                logger.error(f"[Error] Stack trace: {traceback.format_exc()}")
                thread_manager.set_status(thread_id, 'error: server unreachable')
                break
                
            except Exception as e:
                logger.error(f"[Error] Unexpected error in thread {thread_id}: {e}")
                logger.error(f"[Error] URL: {url}")
                import traceback
                logger.error(f"[Error] Stack trace: {traceback.format_exc()}")
                # Check if thread should stop before retrying
                if not thread_manager.is_running(thread_id):
                    break
                thread_manager.set_status(thread_id, f'error: {str(e)[:50]}')
                # Don't retry on errors - just stop the thread
                break
    finally:
        # Clean up all resources
        _cleanup_processing_resources(thread_id, model, settings)

def process_video_stream(url, model_id=None, classifier_id=None, settings_id=None):
    """
    Process video stream from camera server with ML models for VISUALIZATION ONLY.
    
    This function provides real-time visualization of ML processing (detections and classifications)
    WITHOUT any CSV generation or SFTP uploads. It only processes frames for display purposes.
    
    For data collection with CSV/SFTP, use process_video_stream_background() instead.
    
    Args:
        url: URL of the video stream
        model_id: Optional model identifier (name:version)
        classifier_id: Optional classifier identifier (name:version)
        settings_id: Optional settings identifier (name)
    """
    # Load model and settings once before processing stream to avoid repeated database calls
    model = None
    settings = None
    if model_id:
        from computer_vision.ml_model_image_processor import get_model_from_database, get_camera_settings
        try:
            model = get_model_from_database(model_id)
            settings = get_camera_settings(settings_id)  # Use specified settings or default
        except Exception as e:
            logger.error(f"Error loading model or settings: {e}")
    
    # Use SocketManager for proper connection management
    try:
        boundary = b'--frame'
        buffer = b''
        MAX_BUFFER_SIZE = 10 * 1024 * 1024  # 10MB max buffer to prevent memory leak
        
        # Generate unique stream ID for tracking
        import uuid
        stream_id = f"process_stream_{uuid.uuid4().hex[:8]}"
        
        for chunk in socket_manager.stream(stream_id, url, chunk_size=8192):
            buffer += chunk
            
            # Prevent buffer from growing unbounded
            if len(buffer) > MAX_BUFFER_SIZE:
                logger.warning(f"Buffer exceeded {MAX_BUFFER_SIZE} bytes, truncating")
                buffer = buffer[-MAX_BUFFER_SIZE//2:]  # Keep last half
            
            while boundary in buffer:
                start = buffer.find(boundary)
                end = buffer.find(boundary, start + 1)
                if end == -1:
                    break
                
                frame_data = buffer[start:end]
                buffer = buffer[end:]
                
                # Extract JPEG image from frame
                header_end = frame_data.find(b'\r\n\r\n')
                if header_end != -1:
                    jpeg_start = header_end + 4
                    jpeg_end = frame_data.find(b'\r\n', jpeg_start)
                    if jpeg_end == -1:
                        jpeg_data = frame_data[jpeg_start:]
                    else:
                        jpeg_data = frame_data[jpeg_start:jpeg_end]
                    
                    # Decode JPEG to numpy array
                    nparr = np.frombuffer(jpeg_data, np.uint8)
                    img2d = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    
                    if img2d is not None:
                        # Process with ML models if specified
                        if model is not None:
                            try:
                                result = object_process_image(img2d.copy(), model=model, settings=settings)
                                # Annotate image with detection results
                                # result format: [image, xyxy, particles_to_detect, particles_to_save]
                                particles_to_detect = result[2]
                                for i, box in enumerate(result[1]):
                                    cv2.rectangle(img2d, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), (255, 0, 0), 2)
                                    cv2.putText(img2d, f'{particles_to_detect[i].max_d_mm}mm', (int(box[0]), int(box[1]-10)), 
                                              cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
                            except Exception as e:
                                logger.error(f"Error processing with model: {e}")
                        
                        if classifier_id:
                            try:
                                belt_status = classifier_process_image(img2d.copy(), classifier_id=classifier_id)
                                cv2.putText(img2d, f'Status: {belt_status}', (10, 30), 
                                          cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                            except Exception as e:
                                logger.error(f"Error processing with classifier: {e}")
                        
                        # Re-encode processed image
                        _, encoded_img = cv2.imencode('.jpg', img2d)
                        frame_bytes = encoded_img.tobytes()
                        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                        
                        # Explicitly delete to free memory
                        del encoded_img
                        del img2d
                        del nparr
                        del frame_bytes
                    else:
                        # If decode failed, pass through original frame
                        yield frame_data + b'\r\n'
                        del nparr
        
        # Yield any remaining buffer
        if buffer:
            yield buffer
    finally:
        # SocketManager handles connection cleanup automatically
        
        # Explicitly delete model and settings to free memory
        if model is not None:
            try:
                del model
                del settings
            except:
                pass
        
        # Force garbage collection
        import gc
        gc.collect()

# Register cleanup handler to stop all threads when app closes
@atexit.register
def cleanup_threads_on_exit():
    """Stop all managed threads and close all sockets when the application is closing."""
    logger.info("[Shutdown] Application closing, stopping all threads...")
    thread_manager.stop_all_threads(timeout=10.0)
    logger.info("[Shutdown] All threads stopped successfully")
    
    logger.info("[Shutdown] Closing all socket connections...")
    socket_manager.shutdown()
    logger.info("[Shutdown] All sockets closed successfully")

@camera_bp.route('/video')
def video():
    """
    Webcam video endpoint for VISUALIZATION ONLY.
    Returns real-time video feed with optional ML processing visualization.
    Does NOT generate CSV files or upload to SFTP.
    """
    model_param = request.args.get('model')
    classifier_param = request.args.get('classifier')
    settings_param = request.args.get('settings')
    
    # If no processing is requested, use simple passthrough
    if not model_param and not classifier_param:
        return Response(generate_frames(),
                       mimetype='multipart/x-mixed-replace; boundary=frame')
    
    # Otherwise use processing pipeline for visualization
    return Response(process_video_stream(CAMERA_URL, model_param, classifier_param, settings_param),
                   mimetype='multipart/x-mixed-replace; boundary=frame')

@camera_bp.route('/legacy-camera-video/<int:device_id>')
def legacy_camera_video(device_id):
    """
    Legacy camera video endpoint for VISUALIZATION ONLY.
    Returns real-time video feed with optional ML processing visualization.
    Does NOT generate CSV files or upload to SFTP.
    """
    model_param = request.args.get('model')
    classifier_param = request.args.get('classifier')
    settings_param = request.args.get('settings')
    url = config.get_server_video_url('legacy', device_id)
    
    # If no processing is requested, use simple passthrough with SocketManager
    if not model_param and not classifier_param:
        return Response(socket_manager.get_stream_generator(url, chunk_size=1024),
                       mimetype='multipart/x-mixed-replace; boundary=frame')
    
    # Otherwise use processing pipeline for visualization
    return Response(process_video_stream(url, model_param, classifier_param, settings_param),
                   mimetype='multipart/x-mixed-replace; boundary=frame')

@camera_bp.route('/simulator-video')
def simulator_video():
    """
    Simulator video endpoint for VISUALIZATION ONLY.
    Returns real-time video feed with optional ML processing visualization.
    Does NOT generate CSV files or upload to SFTP.
    """
    logger.info("[Simulator Video] Request received")
    model_param = request.args.get('model')
    classifier_param = request.args.get('classifier')
    settings_param = request.args.get('settings')
    url = config.get_server_video_url('simulator')
    
    logger.info(f"[Simulator Video] Connecting to: {url}")
    logger.info(f"[Simulator Video] Model: {model_param}, Classifier: {classifier_param}")
    
    # If no processing is requested, use simple passthrough with SocketManager
    if not model_param and not classifier_param:
        logger.info("[Simulator Video] Using passthrough mode (no ML processing)")
        try:
            return Response(socket_manager.get_stream_generator(url, chunk_size=1024),
                           mimetype='multipart/x-mixed-replace; boundary=frame')
        except Exception as e:
            logger.error(f"[Simulator Video] Error in passthrough: {e}")
            import traceback
            logger.error(f"[Simulator Video] Traceback: {traceback.format_exc()}")
            return Response(f"Error connecting to simulator: {e}", status=503)
    
    # Otherwise use processing pipeline for visualization
    logger.info("[Simulator Video] Using ML processing mode")
    try:
        return Response(process_video_stream(url, model_param, classifier_param, settings_param),
                       mimetype='multipart/x-mixed-replace; boundary=frame')
    except Exception as e:
        logger.error(f"[Simulator Video] Error in ML processing: {e}")
        import traceback
        logger.error(f"[Simulator Video] Traceback: {traceback.format_exc()}")
        return Response(f"Error processing simulator video: {e}", status=503)

@camera_bp.route('/connected-devices')
def connected_devices():
    devices = []
    
    def query_legacy():
        try:
            logger.debug("[Connected Devices] Querying legacy-camera-server (port 5002)...")
            response = socket_manager.get(config.get_server_health_url('legacy'), timeout=config.DEVICE_QUERY_TIMEOUT)
            if response.status_code == 200:
                result = [{'type': 'legacy', 'id': dev['id'], 'info': dev['info'], 
                        'ip': dev['info'].split(';')[0] if ';' in dev['info'] else 'unknown',
                        'status': dev['status']} for dev in response.json()]
                logger.debug(f"[Connected Devices] ✓ Legacy server responded with {len(result)} device(s)")
                return result
        except requests.exceptions.Timeout:
            logger.debug(f"[Connected Devices] ✗ Legacy server timeout")
        except requests.exceptions.ConnectionError:
            logger.debug(f"[Connected Devices] ✗ Legacy server not running")
        except Exception as e:
            logger.warning(f"[Connected Devices] ✗ Legacy server error: {e}")
        return []
    
    def query_webcam():
        try:
            logger.debug("[Connected Devices] Querying webcam-server (port 5001)...")
            response = socket_manager.get(config.get_server_health_url('webcam'), timeout=config.DEVICE_QUERY_TIMEOUT)
            if response.status_code == 200:
                result = [{'type': 'webcam', 'id': dev['id'], 'info': dev['info'],
                        'ip': 'localhost', 'status': dev['status']} for dev in response.json()]
                logger.debug(f"[Connected Devices] ✓ Webcam server responded with {len(result)} device(s)")
                return result
        except requests.exceptions.Timeout:
            logger.debug(f"[Connected Devices] ✗ Webcam server timeout")
        except requests.exceptions.ConnectionError:
            logger.debug(f"[Connected Devices] ✗ Webcam server not running")
        except Exception as e:
            logger.warning(f"[Connected Devices] ✗ Webcam server error: {e}")
        return []
    
    def query_simulator():
        try:
            logger.debug("[Connected Devices] Querying simulator-server (port 5003)...")
            response = socket_manager.get(config.get_server_health_url('simulator'), timeout=config.DEVICE_QUERY_TIMEOUT)
            if response.status_code == 200:
                result = [{'type': 'simulator', 'id': dev['id'], 'info': dev['info'],
                        'ip': 'localhost', 'status': dev['status']} for dev in response.json()]
                logger.debug(f"[Connected Devices] ✓ Simulator server responded with {len(result)} device(s)")
                return result
        except requests.exceptions.Timeout:
            logger.debug(f"[Connected Devices] ✗ Simulator server timeout")
        except requests.exceptions.ConnectionError:
            logger.debug(f"[Connected Devices] ✗ Simulator server not running")
        except Exception as e:
            logger.warning(f"[Connected Devices] ✗ Simulator server error: {e}")
        return []
    
    logger.debug("[Connected Devices] Starting parallel device query...")
    # Execute all queries in parallel with timeout
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(query_legacy),
            executor.submit(query_webcam),
            executor.submit(query_simulator)
        ]
        
        # Use as_completed with timeout to avoid hanging
        try:
            for future in as_completed(futures, timeout=config.DEVICE_QUERY_MAX_WAIT):
                try:
                    devices.extend(future.result())
                except Exception as e:
                    logger.warning(f"[Connected Devices] Query failed: {e}")
        except TimeoutError:
            logger.warning("[Connected Devices] Query timeout - returning partial results")
            # Cancel any pending futures
            for future in futures:
                future.cancel()
    
    logger.debug(f"[Connected Devices] Total devices found: {len(devices)}")
    return jsonify(devices)

@camera_bp.route('/camera-manager')
def camera_manager():
    from sqlite.ml_sqlite_provider import ml_provider
    from flask import make_response
    models = ml_provider.list_models()
    classifiers = ml_provider.list_classifiers()
    
    response = make_response(render_template('camera-manager.html', models=models, classifiers=classifiers))
    # Prevent caching to ensure fresh data on reload
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@camera_bp.route('/start-thread', methods=['POST'])
def start_thread():
    data = request.get_json()
    device_type = data.get('type')
    device_id = data.get('id')
    model_id = data.get('model')
    classifier_id = data.get('classifier')
    settings_id = data.get('settings')
    
    logger.info(f"[Start Thread] Request received:")
    logger.info(f"  Device: {device_type}_{device_id}")
    logger.info(f"  Model ID: '{model_id}' (type: {type(model_id).__name__})")
    logger.info(f"  Classifier ID: '{classifier_id}' (type: {type(classifier_id).__name__})")
    logger.info(f"  Settings ID: '{settings_id}' (type: {type(settings_id).__name__})")
    
    # Convert empty strings to None
    if model_id == '':
        model_id = None
    if classifier_id == '':
        classifier_id = None
    if settings_id == '':
        settings_id = None
    
    logger.info(f"[Start Thread] After conversion: model={model_id}, classifier={classifier_id}, settings={settings_id}")
    
    # Create unique thread ID
    thread_id = f"{device_type}_{device_id}"
    
    # Check if thread already exists
    if thread_manager.is_running(thread_id):
        return jsonify({'error': 'Thread already running for this device'}), 400
    
    # Determine URL based on device type
    if device_type == 'legacy':
        url = config.get_server_video_url('legacy', device_id)
        server_check_url = config.get_server_health_url('legacy')
    elif device_type == 'simulator':
        url = config.get_server_video_url('simulator')
        server_check_url = config.get_server_health_url('simulator')
    else:  # webcam
        url = config.get_server_video_url('webcam')
        server_check_url = config.get_server_health_url('webcam')
    
    # Check if the server is reachable before starting thread (quick check)
    try:
        logger.info(f"[Start Thread] Checking server availability: {server_check_url}")
        check_response = socket_manager.get(server_check_url, timeout=config.THREAD_START_SERVER_CHECK_TIMEOUT)
        if check_response.status_code != 200:
            logger.error(f"[Start Thread] Server check failed with status {check_response.status_code}")
            return jsonify({'error': f'{device_type.capitalize()} server is not responding properly (status {check_response.status_code})'}), 503
        logger.info(f"[Start Thread] Server check OK for {device_type}")
    except requests.exceptions.ConnectionError as e:
        logger.error(f"[Start Thread] Connection error to {server_check_url}: {e}")
        return jsonify({'error': f'{device_type.capitalize()} server on {server_check_url} is not running or unreachable'}), 503
    except requests.exceptions.Timeout as e:
        logger.error(f"[Start Thread] Timeout connecting to {server_check_url}: {e}")
        return jsonify({'error': f'{device_type.capitalize()} server is not responding (timeout)'}), 503
    except Exception as e:
        logger.error(f"[Start Thread] Error checking {server_check_url}: {e}")
        return jsonify({'error': f'Cannot connect to {device_type} server: {str(e)}'}), 503
    
    # Create metadata for the thread
    metadata = {
        'device_type': device_type,
        'device_id': device_id,
        'model_id': model_id or 'None',
        'classifier_id': classifier_id or 'None',
        'settings_id': settings_id or 'default',
        'url': url,
        'frame_count': 0
    }
    
    # Start managed thread
    success = thread_manager.start_thread(
        thread_id=thread_id,
        target=process_video_stream_background,
        args=(thread_id, url, model_id, classifier_id, settings_id),
        metadata=metadata
    )
    
    if not success:
        return jsonify({'error': 'Failed to start thread'}), 500
    
    return jsonify({'success': True, 'thread_id': thread_id})

@camera_bp.route('/stop-thread', methods=['POST'])
def stop_thread():
    data = request.get_json()
    thread_id = data.get('thread_id')
    
    logger.info(f"[Stop Thread] Received request to stop thread: {thread_id}")
    
    # First, forcefully close the stream to interrupt any blocking reads
    socket_manager.close_stream(thread_id)
    
    # Stop the thread using ThreadManager
    # Note: stop_thread returns True if thread stopped OR was already stopped
    success = thread_manager.stop_thread(thread_id, timeout=15.0)
    
    if not success:
        logger.error(f"[Stop Thread] Failed to stop thread {thread_id} - thread exists but won't stop")
        return jsonify({'error': 'Thread exists but failed to stop within timeout'}), 500
    
    logger.info(f"[Stop Thread] Successfully stopped thread: {thread_id}")
    return jsonify({'success': True})

@camera_bp.route('/active-threads')
def get_active_threads():
    # Cleanup old stopped threads
    thread_manager.cleanup_stopped_threads(max_age=60)
    
    # Get all threads from ThreadManager
    all_threads = thread_manager.get_all_threads()
    
    threads_info = []
    for thread_id, info in all_threads.items():
        metadata = info.get('metadata', {})
        threads_info.append({
            'thread_id': thread_id,
            'device_type': metadata.get('device_type', 'unknown'),
            'device_id': metadata.get('device_id', 'unknown'),
            'model_id': metadata.get('model_id', 'None'),
            'classifier_id': metadata.get('classifier_id', 'None'),
            'settings_id': metadata.get('settings_id', 'default'),
            'status': info['status'],
            'running': info['running'],
            'frame_count': metadata.get('frame_count', 0),
            'uptime': info['uptime'],
        })
    
    return jsonify(threads_info)

@camera_bp.route('/system-resources')
def get_system_resources():
    """Monitor system resource usage for debugging performance issues."""
    import psutil
    import os
    import gc
    
    # Get process info
    process = psutil.Process(os.getpid())
    
    # Memory info
    memory_info = process.memory_info()
    memory_mb = memory_info.rss / 1024 / 1024
    
    # CPU info
    cpu_percent = process.cpu_percent(interval=0.1)
    
    # Thread count
    thread_count = process.num_threads()
    
    # Active processing threads from ThreadManager
    active_count = thread_manager.get_active_count()
    total_tracked = thread_manager.get_total_count()
    
    # Active sessions in store manager
    session_count = len(store_data_manager.active_sessions)
    
    # Garbage collection stats
    gc_stats = {
        'collections': gc.get_count(),
        'garbage_objects': len(gc.garbage)
    }
    
    # Socket manager stats
    socket_stats = socket_manager.get_stats()
    
    # Logging stats
    logging_stats = logger.get_stats()
    
    return jsonify({
        'memory_mb': round(memory_mb, 2),
        'cpu_percent': cpu_percent,
        'thread_count': thread_count,
        'active_processing_threads': active_count,
        'total_threads_tracked': total_tracked,
        'active_sessions': session_count,
        'garbage_collection': gc_stats,
        'socket_manager': socket_stats,
        'logging': logging_stats
    })

@camera_bp.route('/csv-writer-stats')
def get_csv_writer_stats():
    """Get CSV writer thread statistics."""
    stats = csv_writer.get_stats()
    is_running = csv_writer.is_running()
    
    return jsonify({
        'running': is_running,
        'stats': stats
    })

@camera_bp.route('/model-detector-stats')
def get_model_detector_stats():
    """Get model detector thread statistics."""
    stats = model_detector.get_stats()
    is_running = model_detector.is_running()
    
    return jsonify({
        'running': is_running,
        'stats': stats
    })

@camera_bp.route('/classifier-processor-stats')
def get_classifier_processor_stats():
    """Get classifier processor thread statistics."""
    stats = classifier_processor.get_stats()
    is_running = classifier_processor.is_running()
    
    return jsonify({
        'running': is_running,
        'stats': stats
    })

@camera_bp.route('/sftp-uploader-stats')
def get_sftp_uploader_stats():
    """Get SFTP uploader thread statistics."""
    stats = sftp_uploader.get_stats()
    is_running = sftp_uploader.is_running()
    
    return jsonify({
        'running': is_running,
        'stats': stats
    })

@camera_bp.route('/cleanup-resources', methods=['POST'])
def cleanup_resources():
    """Manually trigger resource cleanup."""
    import gc
    
    # Cleanup old threads
    thread_manager.cleanup_stopped_threads(max_age=30)
    
    # Cleanup old sessions
    store_data_manager.cleanup_old_sessions()
    
    # Cleanup old streams
    socket_manager.cleanup_old_streams(max_age_seconds=1800)  # 30 minutes
    
    # Force garbage collection
    collected = gc.collect()
    
    return jsonify({
        'success': True,
        'threads_cleaned': 'stopped threads removed',
        'sessions_cleaned': 'old sessions removed',
        'streams_cleaned': 'old streams closed',
        'objects_collected': collected
    })