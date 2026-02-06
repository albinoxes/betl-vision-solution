from flask import Blueprint, render_template, Response, jsonify, request, redirect, url_for
import requests
import cv2
import numpy as np
import time
from datetime import datetime
from computer_vision.ml_model_image_processor import object_process_image, CameraSettings
from computer_vision.classifier_image_processor import classifier_process_image
from storage_data.store_data_manager import store_data_manager
from sqlite.video_stream_sqlite_provider import video_stream_provider
from iris_communication.iris_input_processor import iris_input_processor
from iris_communication.sftp_processor import sftp_processor
from sqlite.sftp_sqlite_provider import sftp_provider
from infrastructure.logging.logging_provider import get_logger
from infrastructure.thread_manager import get_thread_manager
from infrastructure.socket_manager import get_socket_manager
import atexit

# Initialize logger, thread manager, and socket manager
logger = get_logger()
thread_manager = get_thread_manager()
socket_manager = get_socket_manager()

CAMERA_URL = "http://localhost:5001/video"

# Processing interval in seconds - controls how often frames are processed with ML models
PROCESSING_INTERVAL_SECONDS = 1.0  # Process every 1 second

def generate_frames():
    """Generator with proper cleanup to prevent memory leaks."""
    # Use SocketManager for automatic cleanup
    for chunk in socket_manager.get_stream_generator(CAMERA_URL, chunk_size=1024):
        yield chunk

def process_video_stream_background(thread_id, url, model_id=None, classifier_id=None, settings_id=None):
    """
    Process video stream in background thread.
    
    Args:
        thread_id: Unique identifier for this thread
        url: URL of the video stream
        model_id: Optional model identifier (name:version)
        classifier_id: Optional classifier identifier (name:version)
        settings_id: Optional settings identifier (name)
    """
    # Lazy-load models only when needed (not at thread start)
    # This reduces memory usage when models aren't actively processing
    model = None
    settings = None
    model_loaded = False
    
    # Load camera settings before the loop starts
    from sqlite.detection_model_settings_sqlite_provider import detection_model_settings_provider
    if not settings_id:
        # Get the first camera settings from the database
        all_settings = detection_model_settings_provider.list_settings()
        if all_settings and len(all_settings) > 0:
            settings_id = all_settings[0][1]  # Get the name from the first setting
            logger.info(f"[Thread {thread_id}] No settings specified, using first available: {settings_id}")
        else:
            logger.warning(f"[Thread {thread_id}] Warning: No camera settings found in database")
    
    # Get project title and settings once before processing frames
    from sqlite.project_settings_sqlite_provider import project_settings_provider
    project_settings = project_settings_provider.get_project_settings()
    project_title = project_settings.title if project_settings else "default"
    
    # Debug logging for IRIS configuration
    if project_settings:
        logger.info(f"[IRIS] Project settings loaded: {project_title}")
        logger.info(f"[IRIS] Main folder: {project_settings.iris_main_folder}")
        logger.info(f"[IRIS] Model subfolder: {project_settings.iris_model_subfolder}")
        logger.info(f"[IRIS] Classifier subfolder: {project_settings.iris_classifier_subfolder}")
        logger.info(f"[IRIS] Image processing interval: {project_settings.image_processing_interval}s")
        processing_interval = project_settings.image_processing_interval
    else:
        logger.warning(f"[IRIS] Warning: No project settings found!")
        processing_interval = PROCESSING_INTERVAL_SECONDS  # Fallback to hardcoded value
    
    frame_count = 0
    last_model_processing_time = 0  # Track last time model was run
    last_classifier_processing_time = 0  # Track last time classifier was run
    last_frame_save_time = 0  # Track last time frame was saved
    
    # Track previous CSV paths for SFTP upload
    previous_model_csv_path = None
    previous_classifier_csv_path = None
    
    # Get SFTP server info (use the first one if available)
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
                logger.info(f"[Thread {thread_id}] Connecting to video stream...")
                logger.info(f"[Thread {thread_id}] Connected successfully, starting frame processing")
                boundary = b'--frame'
                buffer = b''
                MAX_BUFFER_SIZE = 10 * 1024 * 1024  # 10MB max buffer
                
                # Process chunks with periodic stop checks using SocketManager
                chunk_count = 0
                for chunk in socket_manager.stream(thread_id, url, chunk_size=8192):
                    chunk_count += 1
                    
                    # Check stop flag every 5 chunks for faster response on shutdown
                    if chunk_count % 5 == 0:
                        if not thread_manager.is_running(thread_id):
                            logger.info(f"[Thread {thread_id}] Stop detected in chunk loop, closing stream")
                            socket_manager.close_stream(thread_id)
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
                                # Save frame to storage directory and database at the same interval as processing
                                current_time = time.time()
                                if current_time - last_frame_save_time >= processing_interval:
                                    try:
                                        timestamp = datetime.now()
                                        filename = f"frame_{timestamp.strftime('%Y%m%d_%H%M%S_%f')}.jpg"
                                        
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
                                            except Exception as e:
                                                logger.error(f"Error inserting frame record to database: {e}")
                                        
                                        # Update last frame save time
                                        last_frame_save_time = current_time
                                    except Exception as e:
                                        logger.error(f"Error saving frame: {e}")
                                
                                # Lazy-load model only when we need to process
                                if model_id and not model_loaded:
                                    from computer_vision.ml_model_image_processor import get_model_from_database, get_camera_settings
                                    try:
                                        logger.info(f"[Model] Lazy-loading model: {model_id}, settings: {settings_id}")
                                        model = get_model_from_database(model_id)
                                        settings = get_camera_settings(settings_id)
                                        model_loaded = True
                                        logger.info(f"[Model] Model loaded successfully: {model}")
                                        logger.info(f"[Model] Settings loaded: {settings}")
                                    except Exception as e:
                                        logger.error(f"[Model] Error loading model or settings: {e}")
                                        import traceback
                                        traceback.print_exc()
                                        model = None
                                        settings = None
                                elif model_id and model_loaded:
                                    pass  # Model already loaded
                                else:
                                    if not model_id:
                                        logger.debug(f"[Model] No model_id provided, skipping model processing")
                                
                                # Process with ML models if specified
                                if model is not None:
                                    # Check if processing interval has elapsed
                                    current_time = time.time()
                                    if current_time - last_model_processing_time >= processing_interval:
                                        logger.debug(f"[Processing] Model processing frame at {current_time:.2f}, interval: {current_time - last_model_processing_time:.2f}s")
                                        try:
                                            # Increment frame count for processed frame
                                            frame_count += 1
                                            # Use processing time for CSV timestamp
                                            processing_timestamp = datetime.now()
                                            result = object_process_image(img2d.copy(), model=model, settings=settings)
                                            
                                            # result format: [image, xyxy, particles_to_detect, particles_to_save]
                                            # Use particles_to_detect (index 2) for CSV/reporting
                                            result_for_csv = [result[0], result[1], result[2]]
                                            
                                            # Generate IRIS input CSV for result with processing timestamp
                                            csv_path = iris_input_processor.generate_iris_input_data(
                                                project_settings=project_settings,
                                                timestamp=processing_timestamp,
                                                data=result_for_csv,
                                                folder_type='model',
                                                image_filename=filename
                                            )
                                            
                                            # If a new CSV was created and we have a previous one, upload the previous via SFTP
                                            if csv_path and csv_path != previous_model_csv_path:
                                                if previous_model_csv_path and sftp_server_info:
                                                    try:
                                                        logger.info(f"[SFTP] Uploading previous model CSV: {previous_model_csv_path}")
                                                        upload_result = sftp_processor.transferData(
                                                            sftp_server_info=sftp_server_info,
                                                            file_path=previous_model_csv_path,
                                                            project_settings=project_settings,
                                                            folder_type='model'
                                                        )
                                                        if upload_result['success']:
                                                            logger.info(f"[SFTP] Successfully uploaded: {upload_result['remote_path']}")
                                                        else:
                                                            logger.error(f"[SFTP] Upload failed: {upload_result.get('error', 'Unknown error')}")
                                                    except Exception as e:
                                                        logger.error(f"[SFTP] Error uploading model CSV: {e}")
                                                
                                                # Update to current CSV path
                                                previous_model_csv_path = csv_path
                                            
                                            # Update last processing time
                                            last_model_processing_time = current_time
                                        except Exception as e:
                                            logger.error(f"Error processing with model: {e}")
                                
                                if classifier_id:
                                    # Check if processing interval has elapsed
                                    current_time = time.time()
                                    if current_time - last_classifier_processing_time >= processing_interval:
                                        logger.debug(f"[Processing] Classifier processing frame at {current_time:.2f}, interval: {current_time - last_classifier_processing_time:.2f}s")
                                        try:
                                            # Increment frame count for processed frame (if not already incremented by model)
                                            if not model_id:
                                                frame_count += 1
                                            # Use processing time for CSV timestamp
                                            processing_timestamp = datetime.now()
                                            belt_status = classifier_process_image(img2d.copy(), classifier_id=classifier_id)
                                            # Generate IRIS input CSV for belt status with processing timestamp
                                            csv_path = iris_input_processor.generate_iris_input_data(
                                                project_settings=project_settings,
                                                timestamp=processing_timestamp,
                                                data=belt_status,
                                                folder_type='classifier'
                                            )
                                            
                                            # If a new CSV was created and we have a previous one, upload the previous via SFTP
                                            if csv_path and csv_path != previous_classifier_csv_path:
                                                if previous_classifier_csv_path and sftp_server_info:
                                                    try:
                                                        logger.info(f"[SFTP] Uploading previous classifier CSV: {previous_classifier_csv_path}")
                                                        upload_result = sftp_processor.transferData(
                                                            sftp_server_info=sftp_server_info,
                                                            file_path=previous_classifier_csv_path,
                                                            project_settings=project_settings,
                                                            folder_type='classifier'
                                                        )
                                                        if upload_result['success']:
                                                            logger.info(f"[SFTP] Successfully uploaded: {upload_result['remote_path']}")
                                                        else:
                                                            logger.error(f"[SFTP] Upload failed: {upload_result.get('error', 'Unknown error')}")
                                                    except Exception as e:
                                                        logger.error(f"[SFTP] Error uploading classifier CSV: {e}")
                                                
                                                # Update to current CSV path
                                                previous_classifier_csv_path = csv_path
                                            
                                            # Update last processing time
                                            last_classifier_processing_time = current_time
                                        except Exception as e:
                                            logger.error(f"Error processing with classifier: {e}")
                                
                                # Update frame count
                                thread_manager.update_metadata(thread_id, {
                                    'frame_count': frame_count,
                                    'last_update': time.time()
                                })
                                
                                # Explicitly delete numpy array to free memory
                                del img2d
                                del nparr
                
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
                    thread_manager.set_status(thread_id, 'error: timeout')
                break
                
            except requests.exceptions.ConnectionError as e:
                # Connection error - server might be down
                logger.error(f"[Error] Connection error in thread {thread_id}: Server unreachable or not running")
                thread_manager.set_status(thread_id, 'error: server unreachable')
                break
                
            except Exception as e:
                logger.error(f"[Error] Unexpected error in thread {thread_id}: {e}")
                # Check if thread should stop before retrying
                if not thread_manager.is_running(thread_id):
                    break
                thread_manager.set_status(thread_id, f'error: {str(e)[:50]}')
                # Don't retry on errors - just stop the thread
                break
    finally:
        # Clean up resources
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

def process_video_stream(url, model_id=None, classifier_id=None, settings_id=None):
    """
    Process video stream from camera server with ML models.
    
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

camera_bp = Blueprint('camera', __name__)

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
    model_param = request.args.get('model')
    classifier_param = request.args.get('classifier')
    settings_param = request.args.get('settings')
    
    # If no processing is requested, use simple passthrough
    if not model_param and not classifier_param:
        return Response(generate_frames(),
                       mimetype='multipart/x-mixed-replace; boundary=frame')
    
    # Otherwise use processing pipeline
    return Response(process_video_stream(CAMERA_URL, model_param, classifier_param, settings_param),
                   mimetype='multipart/x-mixed-replace; boundary=frame')

@camera_bp.route('/legacy-camera-video/<int:device_id>')
def legacy_camera_video(device_id):
    model_param = request.args.get('model')
    classifier_param = request.args.get('classifier')
    settings_param = request.args.get('settings')
    url = f"http://localhost:5002/camera-video/{device_id}"
    
    # If no processing is requested, use simple passthrough with SocketManager
    if not model_param and not classifier_param:
        return Response(socket_manager.get_stream_generator(url, chunk_size=1024),
                       mimetype='multipart/x-mixed-replace; boundary=frame')
    
    # Otherwise use processing pipeline
    return Response(process_video_stream(url, model_param, classifier_param, settings_param),
                   mimetype='multipart/x-mixed-replace; boundary=frame')

@camera_bp.route('/simulator-video')
def simulator_video():
    model_param = request.args.get('model')
    classifier_param = request.args.get('classifier')
    settings_param = request.args.get('settings')
    url = "http://localhost:5003/video/simulator"
    
    # If no processing is requested, use simple passthrough with SocketManager
    if not model_param and not classifier_param:
        return Response(socket_manager.get_stream_generator(url, chunk_size=1024),
                       mimetype='multipart/x-mixed-replace; boundary=frame')
    
    # Otherwise use processing pipeline
    return Response(process_video_stream(url, model_param, classifier_param, settings_param),
                   mimetype='multipart/x-mixed-replace; boundary=frame')

@camera_bp.route('/connected-devices')
def connected_devices():
    devices = []
    
    # Use ThreadPoolExecutor to query all servers in parallel
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    def query_legacy():
        try:
            logger.info("[Connected Devices] Querying legacy-camera-server (port 5002)...")
            response = socket_manager.get('http://localhost:5002/devices', timeout=(2, 2))
            if response.status_code == 200:
                result = [{'type': 'legacy', 'id': dev['id'], 'info': dev['info'], 
                        'ip': dev['info'].split(';')[0] if ';' in dev['info'] else 'unknown',
                        'status': dev['status']} for dev in response.json()]
                logger.info(f"[Connected Devices] ✓ Legacy server responded with {len(result)} device(s)")
                return result
        except Exception as e:
            logger.warning(f"[Connected Devices] ✗ Legacy server not responding: {e}")
        return []
    
    def query_webcam():
        try:
            logger.info("[Connected Devices] Querying webcam-server (port 5001)...")
            response = socket_manager.get('http://localhost:5001/devices', timeout=(2, 2))
            if response.status_code == 200:
                result = [{'type': 'webcam', 'id': dev['id'], 'info': dev['info'],
                        'ip': 'localhost', 'status': dev['status']} for dev in response.json()]
                logger.info(f"[Connected Devices] ✓ Webcam server responded with {len(result)} device(s)")
                return result
        except Exception as e:
            logger.warning(f"[Connected Devices] ✗ Webcam server not responding: {e}")
        return []
    
    def query_simulator():
        try:
            logger.info("[Connected Devices] Querying simulator-server (port 5003)...")
            response = socket_manager.get('http://localhost:5003/devices', timeout=(2, 2))
            if response.status_code == 200:
                result = [{'type': 'simulator', 'id': dev['id'], 'info': dev['info'],
                        'ip': 'localhost', 'status': dev['status']} for dev in response.json()]
                logger.info(f"[Connected Devices] ✓ Simulator server responded with {len(result)} device(s)")
                return result
        except Exception as e:
            logger.warning(f"[Connected Devices] ✗ Simulator server not responding: {e}")
        return []
    
    logger.info("[Connected Devices] Starting parallel device query...")
    # Execute all queries in parallel
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(query_legacy),
            executor.submit(query_webcam),
            executor.submit(query_simulator)
        ]
        
        for future in as_completed(futures):
            devices.extend(future.result())
    
    logger.info(f"[Connected Devices] Total devices found: {len(devices)}")
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
        url = f"http://localhost:5002/camera-video/{device_id}"
        server_check_url = "http://localhost:5002/devices"
    elif device_type == 'simulator':
        url = "http://localhost:5003/video/simulator"
        server_check_url = "http://localhost:5003/devices"
    else:  # webcam
        url = "http://localhost:5001/video"
        server_check_url = "http://localhost:5001/devices"
    
    # Check if the server is reachable before starting thread
    try:
        check_response = socket_manager.get(server_check_url, timeout=(2, 2))
        if check_response.status_code != 200:
            return jsonify({'error': f'{device_type.capitalize()} server is not responding properly (status {check_response.status_code})'}), 503
    except requests.exceptions.ConnectionError:
        return jsonify({'error': f'{device_type.capitalize()} server on {server_check_url} is not running or unreachable'}), 503
    except requests.exceptions.Timeout:
        return jsonify({'error': f'{device_type.capitalize()} server is not responding (timeout)'}), 503
    except Exception as e:
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
    
    # Stop the thread using ThreadManager
    success = thread_manager.stop_thread(thread_id, timeout=5.0)
    
    if not success:
        return jsonify({'error': 'Thread not found or failed to stop'}), 404
    
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