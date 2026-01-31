from flask import Blueprint, render_template, Response, jsonify, request, redirect, url_for
import requests
import cv2
import numpy as np
import threading
import time
from datetime import datetime
from computer_vision.ml_model_image_processor import object_process_image, CameraSettings
from computer_vision.classifier_image_processor import classifier_process_image
from storage_data.store_data_manager import store_data_manager
from sqlite.video_stream_sqlite_provider import video_stream_provider
from iris_communication.iris_input_processor import iris_input_processor
from iris_communication.sftp_processor import sftp_processor
from sqlite.sftp_sqlite_provider import sftp_provider

CAMERA_URL = "http://localhost:5001/video"

# Processing interval in seconds - controls how often frames are processed with ML models
PROCESSING_INTERVAL_SECONDS = 1.0  # Process every 1 second

# Global dictionary to track active video processing threads
active_threads = {}
thread_lock = threading.Lock()

def generate_frames():
    r = requests.get(CAMERA_URL, stream=True)
    return Response(r.iter_content(chunk_size=1024),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

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
    from sqlite.camera_settings_sqlite_provider import camera_settings_provider
    if not settings_id:
        # Get the first camera settings from the database
        all_settings = camera_settings_provider.list_settings()
        if all_settings and len(all_settings) > 0:
            settings_id = all_settings[0][1]  # Get the name from the first setting
            print(f"[Thread {thread_id}] No settings specified, using first available: {settings_id}")
        else:
            print(f"[Thread {thread_id}] Warning: No camera settings found in database")
    
    # Get project title and settings once before processing frames
    from sqlite.project_settings_sqlite_provider import project_settings_provider
    project_settings = project_settings_provider.get_project_settings()
    project_title = project_settings.title if project_settings else "default"
    
    # Debug logging for IRIS configuration
    if project_settings:
        print(f"[IRIS] Project settings loaded: {project_title}")
        print(f"[IRIS] Main folder: {project_settings.iris_main_folder}")
        print(f"[IRIS] Model subfolder: {project_settings.iris_model_subfolder}")
        print(f"[IRIS] Classifier subfolder: {project_settings.iris_classifier_subfolder}")
        print(f"[IRIS] Image processing interval: {project_settings.image_processing_interval}s")
        processing_interval = project_settings.image_processing_interval
    else:
        print(f"[IRIS] Warning: No project settings found!")
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
            print(f"[SFTP] Using SFTP server: {sftp_server_info.server_name}")
        else:
            print(f"[SFTP] No SFTP server configured. Files will not be uploaded.")
    except Exception as e:
        print(f"[SFTP] Error loading SFTP server info: {e}")
    
    with thread_lock:
        if thread_id in active_threads:
            active_threads[thread_id]['status'] = 'running'
            active_threads[thread_id]['frame_count'] = 0
    
    # Don't use a persistent session to avoid socket issues on Windows
    # Create new connection for each request cycle
    current_request = None
    
    print(f"[Thread {thread_id}] Starting stream processing")
    print(f"[Thread {thread_id}] URL: {url}")
    print(f"[Thread {thread_id}] Model ID: {model_id}, Classifier ID: {classifier_id}, Settings ID: {settings_id}")
    
    try:
        while True:
            # Check if thread should stop
            with thread_lock:
                if thread_id not in active_threads or not active_threads[thread_id]['running']:
                    break
            
            try:
                # Use timeout only for connection, not for reading stream (None for read timeout)
                print(f"[Thread {thread_id}] Connecting to video stream...")
                # Don't reuse connections - create fresh request each time
                current_request = requests.get(url, stream=True, timeout=(5, None))
                r = current_request
                print(f"[Thread {thread_id}] Connected successfully, starting frame processing")
                boundary = b'--frame'
                buffer = b''
                
                # Process chunks with periodic stop checks
                chunk_count = 0
                for chunk in r.iter_content(chunk_size=8192):
                    chunk_count += 1
                    
                    # Check stop flag every 10 chunks (not on every chunk for performance)
                    if chunk_count % 10 == 0:
                        with thread_lock:
                            if thread_id not in active_threads or not active_threads[thread_id]['running']:
                                r.close()
                                break
                    
                    buffer += chunk
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
                                # Increment frame count for each decoded frame
                                frame_count += 1
                                
                                # Log frame reception (only once every 100 frames to avoid spam)
                                if frame_count % 100 == 0:
                                    print(f"[Thread {thread_id}] Processed {frame_count} frames")
                                
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
                                                print(f"Error inserting frame record to database: {e}")
                                        
                                        # Update last frame save time
                                        last_frame_save_time = current_time
                                    except Exception as e:
                                        print(f"Error saving frame: {e}")
                                
                                # Lazy-load model only when we need to process
                                if model_id and not model_loaded:
                                    from computer_vision.ml_model_image_processor import get_model_from_database, get_camera_settings
                                    try:
                                        print(f"[Model] Lazy-loading model: {model_id}, settings: {settings_id}")
                                        model = get_model_from_database(model_id)
                                        settings = get_camera_settings(settings_id)
                                        model_loaded = True
                                        print(f"[Model] Model loaded successfully: {model}")
                                        print(f"[Model] Settings loaded: {settings}")
                                    except Exception as e:
                                        print(f"[Model] Error loading model or settings: {e}")
                                        import traceback
                                        traceback.print_exc()
                                        model = None
                                        settings = None
                                elif model_id and model_loaded:
                                    pass  # Model already loaded
                                else:
                                    if not model_id:
                                        print(f"[Model] No model_id provided, skipping model processing")
                                
                                # Process with ML models if specified
                                if model is not None:
                                    # Check if processing interval has elapsed
                                    current_time = time.time()
                                    if current_time - last_model_processing_time >= processing_interval:
                                        print(f"[Processing] Model processing frame at {current_time:.2f}, interval: {current_time - last_model_processing_time:.2f}s")
                                        try:
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
                                                        print(f"[SFTP] Uploading previous model CSV: {previous_model_csv_path}")
                                                        upload_result = sftp_processor.transferData(
                                                            sftp_server_info=sftp_server_info,
                                                            file_path=previous_model_csv_path,
                                                            project_settings=project_settings,
                                                            folder_type='model'
                                                        )
                                                        if upload_result['success']:
                                                            print(f"[SFTP] Successfully uploaded: {upload_result['remote_path']}")
                                                        else:
                                                            print(f"[SFTP] Upload failed: {upload_result.get('error', 'Unknown error')}")
                                                    except Exception as e:
                                                        print(f"[SFTP] Error uploading model CSV: {e}")
                                                
                                                # Update to current CSV path
                                                previous_model_csv_path = csv_path
                                            
                                            # Update last processing time
                                            last_model_processing_time = current_time
                                        except Exception as e:
                                            print(f"Error processing with model: {e}")
                                
                                if classifier_id:
                                    # Check if processing interval has elapsed
                                    current_time = time.time()
                                    if current_time - last_classifier_processing_time >= processing_interval:
                                        print(f"[Processing] Classifier processing frame at {current_time:.2f}, interval: {current_time - last_classifier_processing_time:.2f}s")
                                        try:
                                            # Use processing time for CSV timestamp
                                            processing_timestamp = datetime.now()
                                            belt_status = classifier_process_image(img2d.copy(), classifier_id=classifier_id)
                                            frame_count += 1
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
                                                        print(f"[SFTP] Uploading previous classifier CSV: {previous_classifier_csv_path}")
                                                        upload_result = sftp_processor.transferData(
                                                            sftp_server_info=sftp_server_info,
                                                            file_path=previous_classifier_csv_path,
                                                            project_settings=project_settings,
                                                            folder_type='classifier'
                                                        )
                                                        if upload_result['success']:
                                                            print(f"[SFTP] Successfully uploaded: {upload_result['remote_path']}")
                                                        else:
                                                            print(f"[SFTP] Upload failed: {upload_result.get('error', 'Unknown error')}")
                                                    except Exception as e:
                                                        print(f"[SFTP] Error uploading classifier CSV: {e}")
                                                
                                                # Update to current CSV path
                                                previous_classifier_csv_path = csv_path
                                            
                                            # Update last processing time
                                            last_classifier_processing_time = current_time
                                        except Exception as e:
                                            print(f"Error processing with classifier: {e}")
                                
                                # Update frame count
                                with thread_lock:
                                    if thread_id in active_threads:
                                        active_threads[thread_id]['frame_count'] = frame_count
                                        active_threads[thread_id]['last_update'] = time.time()
                
                # Close the response properly
                if current_request:
                    current_request.close()
                
                # If we got here without errors, break the retry loop
                # to avoid unnecessary reconnections
                break
                
            except requests.exceptions.Timeout as e:
                # Timeout error - don't retry, just stop
                print(f"[Error] Timeout in thread {thread_id}: {e}")
                with thread_lock:
                    if thread_id in active_threads:
                        active_threads[thread_id]['status'] = 'error: timeout'
                break
                
            except requests.exceptions.ConnectionError as e:
                # Connection error - server might be down
                print(f"[Error] Connection error in thread {thread_id}: Server unreachable or not running")
                with thread_lock:
                    if thread_id in active_threads:
                        active_threads[thread_id]['status'] = 'error: server unreachable'
                break
                
            except Exception as e:
                print(f"[Error] Unexpected error in thread {thread_id}: {e}")
                # Check if thread should stop before retrying
                with thread_lock:
                    if thread_id not in active_threads or not active_threads[thread_id]['running']:
                        break
                    active_threads[thread_id]['status'] = f'error: {str(e)[:50]}'
                # Don't retry on errors - just stop the thread
                break
    finally:
        # Clean up resources
        print(f"[Cleanup] Stopping thread {thread_id}")
        
        # Explicitly delete model to free memory
        if model is not None:
            try:
                del model
                del settings
                print(f"[Cleanup] ML model unloaded from memory")
            except:
                pass
        
        # Clean up session tracking
        try:
            store_data_manager.end_session(thread_id)
        except Exception as e:
            print(f"Error ending session: {e}")
        
        # Close any open request
        if current_request:
            try:
                print(f"[Cleanup] Closing HTTP connection for thread {thread_id}")
                current_request.close()
                # Force close the underlying connection
                if hasattr(current_request, 'raw'):
                    current_request.raw.close()
            except Exception as e:
                print(f"[Cleanup] Error closing request: {e}")
            
        with thread_lock:
            if thread_id in active_threads:
                active_threads[thread_id]['status'] = 'stopped'
                active_threads[thread_id]['running'] = False

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
            print(f"Error loading model or settings: {e}")
    
    r = requests.get(url, stream=True)
    boundary = b'--frame'
    buffer = b''
    
    for chunk in r.iter_content(chunk_size=8192):
        buffer += chunk
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
                            print(f"Error processing with model: {e}")
                    
                    if classifier_id:
                        try:
                            belt_status = classifier_process_image(img2d.copy(), classifier_id=classifier_id)
                            cv2.putText(img2d, f'Status: {belt_status}', (10, 30), 
                                      cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                        except Exception as e:
                            print(f"Error processing with classifier: {e}")
                    
                    # Re-encode processed image
                    _, encoded_img = cv2.imencode('.jpg', img2d)
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + encoded_img.tobytes() + b'\r\n')
                else:
                    # If decode failed, pass through original frame
                    yield frame_data + b'\r\n'
    
    # Yield any remaining buffer
    if buffer:
        yield buffer

camera_bp = Blueprint('camera', __name__)

@camera_bp.route('/video')
def video():
    model_param = request.args.get('model')
    classifier_param = request.args.get('classifier')
    settings_param = request.args.get('settings')
    
    # If no processing is requested, use simple passthrough
    if not model_param and not classifier_param:
        return generate_frames()
    
    # Otherwise use processing pipeline
    return Response(process_video_stream(CAMERA_URL, model_param, classifier_param, settings_param),
                   mimetype='multipart/x-mixed-replace; boundary=frame')

@camera_bp.route('/legacy-camera-video/<int:device_id>')
def legacy_camera_video(device_id):
    model_param = request.args.get('model')
    classifier_param = request.args.get('classifier')
    settings_param = request.args.get('settings')
    url = f"http://localhost:5002/camera-video/{device_id}"
    
    # If no processing is requested, use simple passthrough
    if not model_param and not classifier_param:
        r = requests.get(url, stream=True)
        return Response(r.iter_content(chunk_size=1024),
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
    
    # If no processing is requested, use simple passthrough
    if not model_param and not classifier_param:
        r = requests.get(url, stream=True)
        return Response(r.iter_content(chunk_size=1024),
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
            print("[Connected Devices] Querying legacy-camera-server (port 5002)...")
            response = requests.get('http://localhost:5002/devices', timeout=2)
            if response.status_code == 200:
                result = [{'type': 'legacy', 'id': dev['id'], 'info': dev['info'], 
                        'ip': dev['info'].split(';')[0] if ';' in dev['info'] else 'unknown',
                        'status': dev['status']} for dev in response.json()]
                print(f"[Connected Devices] ✓ Legacy server responded with {len(result)} device(s)")
                return result
        except Exception as e:
            print(f"[Connected Devices] ✗ Legacy server not responding: {e}")
        return []
    
    def query_webcam():
        try:
            print("[Connected Devices] Querying webcam-server (port 5001)...")
            response = requests.get('http://localhost:5001/devices', timeout=2)
            if response.status_code == 200:
                result = [{'type': 'webcam', 'id': dev['id'], 'info': dev['info'],
                        'ip': 'localhost', 'status': dev['status']} for dev in response.json()]
                print(f"[Connected Devices] ✓ Webcam server responded with {len(result)} device(s)")
                return result
        except Exception as e:
            print(f"[Connected Devices] ✗ Webcam server not responding: {e}")
        return []
    
    def query_simulator():
        try:
            print("[Connected Devices] Querying simulator-server (port 5003)...")
            response = requests.get('http://localhost:5003/devices', timeout=2)
            if response.status_code == 200:
                result = [{'type': 'simulator', 'id': dev['id'], 'info': dev['info'],
                        'ip': 'localhost', 'status': dev['status']} for dev in response.json()]
                print(f"[Connected Devices] ✓ Simulator server responded with {len(result)} device(s)")
                return result
        except Exception as e:
            print(f"[Connected Devices] ✗ Simulator server not responding: {e}")
        return []
    
    print("[Connected Devices] Starting parallel device query...")
    # Execute all queries in parallel
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(query_legacy),
            executor.submit(query_webcam),
            executor.submit(query_simulator)
        ]
        
        for future in as_completed(futures):
            devices.extend(future.result())
    
    print(f"[Connected Devices] Total devices found: {len(devices)}")
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

@camera_bp.route('/add-camera-settings', methods=['POST'])
def add_camera_settings():
    from sqlite.camera_settings_sqlite_provider import camera_settings_provider

    # Extract form data
    name = request.form.get('name')
    if not name:
        return "Name is required", 400
    
    # Use CameraSettings class to define defaults and extract values
    min_conf = float(request.form.get('min_conf', 0.8))
    min_d_detect = int(request.form.get('min_d_detect', 200))
    min_d_save = int(request.form.get('min_d_save', 200))
    max_d_detect = int(request.form.get('max_d_detect', 10000))
    max_d_save = int(request.form.get('max_d_save', 10000))
    particle_bb_dimension_factor = float(request.form.get('particle_bb_dimension_factor', 0.9))
    est_particle_volume_x = float(request.form.get('est_particle_volume_x', 8.357470139e-11))
    est_particle_volume_exp = float(request.form.get('est_particle_volume_exp', 3.02511466443))
    
    camera_settings_provider.insert_settings(
        name, 
        min_conf, 
        min_d_detect, 
        min_d_save,
        max_d_detect,
        max_d_save,
        particle_bb_dimension_factor, 
        est_particle_volume_x, 
        est_particle_volume_exp
    )
    return redirect(url_for('camera.camera_manager'))

@camera_bp.route('/update-camera-settings/<setting_name>', methods=['POST'])
def update_camera_settings(setting_name):
    from sqlite.camera_settings_sqlite_provider import camera_settings_provider

    # Define update fields mapping
    update_fields = [
        ('min_conf', float),
        ('min_d_detect', int),
        ('min_d_save', int),
        ('max_d_detect', int),
        ('max_d_save', int),
        ('particle_bb_dimension_factor', float),
        ('est_particle_volume_x', float),
        ('est_particle_volume_exp', float)
    ]
    
    updates = {}
    for field_name, field_type in update_fields:
        value = request.form.get(field_name)
        if value:
            updates[field_name] = field_type(value)

    camera_settings_provider.update_settings(setting_name, **updates)
    # Add timestamp to force cache refresh
    import time
    return redirect(url_for('camera.camera_manager') + f'?t={int(time.time())}')

@camera_bp.route('/delete-camera-settings/<setting_name>', methods=['POST'])
def delete_camera_settings(setting_name):
    from sqlite.camera_settings_sqlite_provider import camera_settings_provider
    camera_settings_provider.delete_settings(setting_name)
    return redirect(url_for('camera.camera_manager'))

@camera_bp.route('/start-thread', methods=['POST'])
def start_thread():
    data = request.get_json()
    device_type = data.get('type')
    device_id = data.get('id')
    model_id = data.get('model')
    classifier_id = data.get('classifier')
    settings_id = data.get('settings')
    
    print(f"[Start Thread] Request received:")
    print(f"  Device: {device_type}_{device_id}")
    print(f"  Model ID: '{model_id}' (type: {type(model_id).__name__})")
    print(f"  Classifier ID: '{classifier_id}' (type: {type(classifier_id).__name__})")
    print(f"  Settings ID: '{settings_id}' (type: {type(settings_id).__name__})")
    
    # Convert empty strings to None
    if model_id == '':
        model_id = None
    if classifier_id == '':
        classifier_id = None
    if settings_id == '':
        settings_id = None
    
    print(f"[Start Thread] After conversion: model={model_id}, classifier={classifier_id}, settings={settings_id}")
    
    # Create unique thread ID
    thread_id = f"{device_type}_{device_id}"
    
    # Check if thread already exists
    with thread_lock:
        if thread_id in active_threads and active_threads[thread_id]['running']:
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
        check_response = requests.get(server_check_url, timeout=2)
        if check_response.status_code != 200:
            return jsonify({'error': f'{device_type.capitalize()} server is not responding properly (status {check_response.status_code})'}), 503
    except requests.exceptions.ConnectionError:
        return jsonify({'error': f'{device_type.capitalize()} server on {server_check_url} is not running or unreachable'}), 503
    except requests.exceptions.Timeout:
        return jsonify({'error': f'{device_type.capitalize()} server is not responding (timeout)'}), 503
    except Exception as e:
        return jsonify({'error': f'Cannot connect to {device_type} server: {str(e)}'}), 503
    
    # Create and start thread
    thread = threading.Thread(
        target=process_video_stream_background,
        args=(thread_id, url, model_id, classifier_id, settings_id),
        daemon=True
    )
    
    with thread_lock:
        active_threads[thread_id] = {
            'thread': thread,
            'running': True,
            'status': 'starting',
            'device_type': device_type,
            'device_id': device_id,
            'model_id': model_id or 'None',
            'classifier_id': classifier_id or 'None',
            'settings_id': settings_id or 'default',
            'url': url,
            'frame_count': 0,
            'start_time': time.time(),
            'last_update': time.time()
        }
    
    thread.start()
    return jsonify({'success': True, 'thread_id': thread_id})

@camera_bp.route('/stop-thread', methods=['POST'])
def stop_thread():
    data = request.get_json()
    thread_id = data.get('thread_id')
    
    thread_obj = None
    
    with thread_lock:
        if thread_id not in active_threads:
            return jsonify({'error': 'Thread not found'}), 404
        
        active_threads[thread_id]['running'] = False
        active_threads[thread_id]['status'] = 'stopping'
        thread_obj = active_threads[thread_id].get('thread')
    
    print(f"[Stop Thread] Stopping thread {thread_id}...")
    
    # Wait for thread to actually stop (max 5 seconds)
    if thread_obj and thread_obj.is_alive():
        thread_obj.join(timeout=5)
        if thread_obj.is_alive():
            print(f"[Stop Thread] Warning: Thread {thread_id} did not stop gracefully")
        else:
            print(f"[Stop Thread] Thread {thread_id} stopped successfully")
    
    # Clean up thread from active_threads after stopping
    with thread_lock:
        if thread_id in active_threads:
            active_threads[thread_id]['status'] = 'stopped'
    
    return jsonify({'success': True})

@camera_bp.route('/active-threads')
def get_active_threads():
    threads_info = []
    with thread_lock:
        for thread_id, info in list(active_threads.items()):
            # Remove stopped threads that have been stopped for more than 60 seconds
            if not info['running'] and time.time() - info.get('last_update', 0) > 60:
                del active_threads[thread_id]
                continue
            
            threads_info.append({
                'thread_id': thread_id,
                'device_type': info['device_type'],
                'device_id': info['device_id'],
                'model_id': info['model_id'],
                'classifier_id': info['classifier_id'],
                'settings_id': info['settings_id'],
                'status': info['status'],
                'running': info['running'],
                'frame_count': info['frame_count'],
                'uptime': int(time.time() - info['start_time']),
            })
    
    return jsonify(threads_info)

@camera_bp.route('/system-resources')
def get_system_resources():
    """Monitor system resource usage for debugging performance issues."""
    import psutil
    import os
    
    # Get process info
    process = psutil.Process(os.getpid())
    
    # Memory info
    memory_info = process.memory_info()
    memory_mb = memory_info.rss / 1024 / 1024
    
    # CPU info
    cpu_percent = process.cpu_percent(interval=0.1)
    
    # Thread count
    thread_count = process.num_threads()
    
    # Active processing threads
    with thread_lock:
        active_count = sum(1 for t in active_threads.values() if t['running'])
    
    return jsonify({
        'memory_mb': round(memory_mb, 2),
        'cpu_percent': cpu_percent,
        'thread_count': thread_count,
        'active_processing_threads': active_count,
        'total_threads_tracked': len(active_threads)
    })