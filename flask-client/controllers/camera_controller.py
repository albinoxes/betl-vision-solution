from flask import Blueprint, render_template, Response, jsonify, request, redirect, url_for
import requests
import cv2
import numpy as np
import threading
import time
from computer_vision.ml_model_image_processor import object_process_image, CameraSettings
from computer_vision.classifier_image_processor import classifier_process_image

CAMERA_URL = "http://localhost:5001/video"

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
    # Load model and settings once
    model = None
    settings = None
    if model_id:
        from computer_vision.ml_model_image_processor import get_model_from_database, get_camera_settings
        try:
            model = get_model_from_database(model_id)
            settings = get_camera_settings(settings_id)
        except Exception as e:
            print(f"Error loading model or settings: {e}")
    
    frame_count = 0
    with thread_lock:
        if thread_id in active_threads:
            active_threads[thread_id]['status'] = 'running'
            active_threads[thread_id]['frame_count'] = 0
    
    # Create a session that can be closed from outside
    session = requests.Session()
    current_request = None
    
    # Store session in thread info so we can close it externally
    with thread_lock:
        if thread_id in active_threads:
            active_threads[thread_id]['session'] = session
    
    try:
        while True:
            # Check if thread should stop
            with thread_lock:
                if thread_id not in active_threads or not active_threads[thread_id]['running']:
                    break
            
            try:
                # Use timeout only for connection, not for reading stream (None for read timeout)
                current_request = session.get(url, stream=True, timeout=(5, None))
                r = current_request
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
                                # Process with ML models if specified
                                if model is not None:
                                    try:
                                        result = object_process_image(img2d.copy(), model=model, settings=settings)
                                        frame_count += 1
                                    except Exception as e:
                                        print(f"Error processing with model: {e}")
                                
                                if classifier_id:
                                    try:
                                        belt_status = classifier_process_image(img2d.copy(), classifier_id=classifier_id)
                                        frame_count += 1
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
                print(f"Timeout in thread {thread_id}: {e}")
                break
                
            except Exception as e:
                print(f"Error in thread {thread_id}: {e}")
                # Check if thread should stop before retrying
                with thread_lock:
                    if thread_id not in active_threads or not active_threads[thread_id]['running']:
                        break
                # Don't retry on errors - just stop the thread
                break
    finally:
        # Close any open request
        if current_request:
            try:
                current_request.close()
            except:
                pass
        
        # Close the session
        try:
            session.close()
        except:
            pass
            
        with thread_lock:
            if thread_id in active_threads:
                active_threads[thread_id]['status'] = 'stopped'
                active_threads[thread_id]['running'] = False
                # Remove session reference
                active_threads[thread_id].pop('session', None)

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
                            # result format: [image, xyxy, particles]
                            particles = result[2]
                            for i, box in enumerate(result[1]):
                                cv2.rectangle(img2d, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), (255, 0, 0), 2)
                                cv2.putText(img2d, f'{particles[i].max_d_mm}mm', (int(box[0]), int(box[1]-10)), 
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
    
    # Query legacy-camera-server
    try:
        legacy_response = requests.get('http://localhost:5002/devices', timeout=3)
        if legacy_response.status_code == 200:
            legacy_devices = legacy_response.json()
            for dev in legacy_devices:
                devices.append({
                    'type': 'legacy',
                    'id': dev['id'],
                    'info': dev['info'],
                    'ip': dev['info'].split(';')[0] if ';' in dev['info'] else 'unknown',
                    'status': dev['status']
                })
    except Exception as e:
        pass  # Server not running or error

    # Query webcam-server
    try:
        webcam_response = requests.get('http://localhost:5001/devices', timeout=3)
        if webcam_response.status_code == 200:
            webcam_devices = webcam_response.json()
            for dev in webcam_devices:
                devices.append({
                    'type': 'webcam',
                    'id': dev['id'],
                    'info': dev['info'],
                    'ip': 'localhost',
                    'status': dev['status']
                })
    except Exception as e:
        pass  # Server not running or error

    # Query simulator-server
    try:
        simulator_response = requests.get('http://localhost:5003/devices', timeout=3)
        if simulator_response.status_code == 200:
            simulator_devices = simulator_response.json()
            for dev in simulator_devices:
                devices.append({
                    'type': 'simulator',
                    'id': dev['id'],
                    'info': dev['info'],
                    'ip': 'localhost',
                    'status': dev['status']
                })
    except Exception as e:
        pass  # Server not running or error

    return jsonify(devices)

@camera_bp.route('/camera-manager')
def camera_manager():
    from sqlite.ml_sqlite_provider import ml_provider
    from sqlite.camera_settings_sqlite_provider import camera_settings_provider
    models = ml_provider.list_models()
    classifiers = ml_provider.list_classifiers()
    settings = camera_settings_provider.list_settings()
    return render_template('camera-manager.html', models=models, classifiers=classifiers, settings=settings)

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
    particle_bb_dimension_factor = float(request.form.get('particle_bb_dimension_factor', 0.9))
    est_particle_volume_x = float(request.form.get('est_particle_volume_x', 8.357470139e-11))
    est_particle_volume_exp = float(request.form.get('est_particle_volume_exp', 3.02511466443))
    
    camera_settings_provider.insert_settings(
        name, 
        min_conf, 
        min_d_detect, 
        min_d_save, 
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
    return redirect(url_for('camera.camera_manager'))

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
    
    # Create unique thread ID
    thread_id = f"{device_type}_{device_id}"
    
    # Check if thread already exists
    with thread_lock:
        if thread_id in active_threads and active_threads[thread_id]['running']:
            return jsonify({'error': 'Thread already running for this device'}), 400
    
    # Determine URL based on device type
    if device_type == 'legacy':
        url = f"http://localhost:5002/camera-video/{device_id}"
    elif device_type == 'simulator':
        url = "http://localhost:5003/video/simulator"
    else:  # webcam
        url = "http://localhost:5001/video"
    
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
    session_obj = None
    
    with thread_lock:
        if thread_id in active_threads:
            active_threads[thread_id]['running'] = False
            thread_obj = active_threads[thread_id].get('thread')
            session_obj = active_threads[thread_id].get('session')
    
    # Force close the session to interrupt any blocking reads
    if session_obj:
        try:
            session_obj.close()
        except:
            pass
    
    # Wait for thread to actually stop (max 3 seconds)
    if thread_obj and thread_obj.is_alive():
        thread_obj.join(timeout=3)
    
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