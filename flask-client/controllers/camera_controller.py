from flask import Blueprint, render_template, Response, jsonify, request, redirect, url_for
import requests
import cv2
import numpy as np
from computer_vision.ml_model_image_processor import object_process_image
from computer_vision.classifier_image_processor import classifier_process_image
import torch
import torchvision.transforms as transforms

CAMERA_URL = "http://localhost:5001/video"

# Constants for processing
min_conf = 0.8
pixels_per_mm = 1 / (900 / 240)
particle_bb_dimension_factor = 0.9
est_particle_volume_x = 0.00000000008357470139
est_particle_volume_exp = 3.02511466443
class_names = ['0', '2', '1']
transform = transforms.Compose([transforms.Resize((150, 150)),
                                transforms.ToTensor(),
                                transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))])

def generate_frames(model_param=None, classifier_param=None):
    ml_model = None
    classifier_model = None
    if model_param:
        name, version = model_param.split(':', 1) if ':' in model_param else (model_param, '1.0.0')
        from sqlite.ml_sqlite_provider import ml_provider
        ml_model = ml_provider.load_ml_model(name, version)
    if classifier_param:
        name, version = classifier_param.split(':', 1) if ':' in classifier_param else (classifier_param, '1.0.0')
        if not 'ml_provider' in locals():
            from sqlite.ml_sqlite_provider import ml_provider
        classifier_model = ml_provider.load_ml_model(name, version)
    
    r = requests.get(CAMERA_URL, stream=True)
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
            # extract jpeg
            header_end = frame_data.find(b'\r\n\r\n')
            if header_end != -1:
                jpeg_start = header_end + 4
                jpeg_end = frame_data.find(b'\r\n', jpeg_start)
                if jpeg_end == -1:
                    jpeg_data = frame_data[jpeg_start:]
                else:
                    jpeg_data = frame_data[jpeg_start:jpeg_end]
                # decode
                nparr = np.frombuffer(jpeg_data, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if img is not None:
                    # process
                    if ml_model:
                        result = object_process_image(img.copy(), ml_model, min_conf, pixels_per_mm, particle_bb_dimension_factor, est_particle_volume_x, est_particle_volume_exp)
                        # annotate
                        for i, box in enumerate(result[1]):
                            cv2.rectangle(img, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), (255, 0, 0), 2)
                            cv2.putText(img, f'{result[7][i]}mm', (int(box[0]), int(box[1]-10)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,0,0), 1)
                    if classifier_model:
                        belt_status = classifier_process_image(img.copy(), classifier_model, class_names, transform)
                        cv2.putText(img, f'Status: {belt_status}', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)
                    # re-encode
                    _, encoded_img = cv2.imencode('.jpg', img)
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + encoded_img.tobytes() + b'\r\n')
                else:
                    yield frame_data + b'\r\n'
    if buffer:
        yield buffer

def generate_legacy_frames(url, model_param=None, classifier_param=None):
    ml_model = None
    classifier_model = None
    if model_param:
        name, version = model_param.split(':', 1) if ':' in model_param else (model_param, '1.0.0')
        from sqlite.ml_sqlite_provider import ml_provider
        ml_model = ml_provider.load_ml_model(name, version)
    if classifier_param:
        name, version = classifier_param.split(':', 1) if ':' in classifier_param else (classifier_param, '1.0.0')
        if not 'ml_provider' in locals():
            from sqlite.ml_sqlite_provider import ml_provider
        classifier_model = ml_provider.load_ml_model(name, version)
    
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
            # extract jpeg
            header_end = frame_data.find(b'\r\n\r\n')
            if header_end != -1:
                jpeg_start = header_end + 4
                jpeg_end = frame_data.find(b'\r\n', jpeg_start)
                if jpeg_end == -1:
                    jpeg_data = frame_data[jpeg_start:]
                else:
                    jpeg_data = frame_data[jpeg_start:jpeg_end]
                # decode
                nparr = np.frombuffer(jpeg_data, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if img is not None:
                    # process
                    if ml_model:
                        result = object_process_image(img.copy(), ml_model, min_conf, pixels_per_mm, particle_bb_dimension_factor, est_particle_volume_x, est_particle_volume_exp)
                        # annotate
                        for i, box in enumerate(result[1]):
                            cv2.rectangle(img, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), (255, 0, 0), 2)
                            cv2.putText(img, f'{result[7][i]}mm', (int(box[0]), int(box[1]-10)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,0,0), 1)
                    if classifier_model:
                        belt_status = classifier_process_image(img.copy(), classifier_model, class_names, transform)
                        cv2.putText(img, f'Status: {belt_status}', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)
                    # re-encode
                    _, encoded_img = cv2.imencode('.jpg', img)
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + encoded_img.tobytes() + b'\r\n')
                else:
                    yield frame_data + b'\r\n'
    if buffer:
        yield buffer

camera_bp = Blueprint('camera', __name__)

@camera_bp.route('/video')
def video():
    model_param = request.args.get('model')
    classifier_param = request.args.get('classifier')
    return generate_frames(model_param, classifier_param)

@camera_bp.route('/legacy-camera-video/<int:device_id>')
def legacy_camera_video(device_id):
    model_param = request.args.get('model')
    classifier_param = request.args.get('classifier')
    url = f"http://localhost:5002/camera-video/{device_id}"
    return generate_legacy_frames(url, model_param, classifier_param)

@camera_bp.route('/connected-devices')
def connected_devices():
    devices = []
    try:
        # Query legacy-camera-server
        legacy_response = requests.get('http://localhost:5002/devices', timeout=5)
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
    except:
        pass  # Server not running or error

    try:
        # Query webcam-server
        webcam_response = requests.get('http://localhost:5001/devices', timeout=5)
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
    except:
        pass

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

    name = request.form.get('name')
    min_conf = float(request.form.get('min_conf', 0.8))
    min_d_detect = int(request.form.get('min_d_detect', 200))
    min_d_save = int(request.form.get('min_d_save', 200))
    particle_bb_dimension_factor = float(request.form.get('particle_bb_dimension_factor', 0.9))
    est_particle_volume_x = float(request.form.get('est_particle_volume_x', 8.357470139e-11))
    est_particle_volume_exp = float(request.form.get('est_particle_volume_exp', 3.02511466443))

    if not name:
        return "Name is required", 400

    camera_settings_provider.insert_settings(name, min_conf, min_d_detect, min_d_save, particle_bb_dimension_factor, est_particle_volume_x, est_particle_volume_exp)
    return redirect(url_for('camera.camera_manager'))

@camera_bp.route('/update-camera-settings/<setting_name>', methods=['POST'])
def update_camera_settings(setting_name):
    from sqlite.camera_settings_sqlite_provider import camera_settings_provider

    min_conf = request.form.get('min_conf')
    min_d_detect = request.form.get('min_d_detect')
    min_d_save = request.form.get('min_d_save')
    particle_bb_dimension_factor = request.form.get('particle_bb_dimension_factor')
    est_particle_volume_x = request.form.get('est_particle_volume_x')
    est_particle_volume_exp = request.form.get('est_particle_volume_exp')

    updates = {}
    if min_conf:
        updates['min_conf'] = float(min_conf)
    if min_d_detect:
        updates['min_d_detect'] = int(min_d_detect)
    if min_d_save:
        updates['min_d_save'] = int(min_d_save)
    if particle_bb_dimension_factor:
        updates['particle_bb_dimension_factor'] = float(particle_bb_dimension_factor)
    if est_particle_volume_x:
        updates['est_particle_volume_x'] = float(est_particle_volume_x)
    if est_particle_volume_exp:
        updates['est_particle_volume_exp'] = float(est_particle_volume_exp)

    camera_settings_provider.update_settings(setting_name, **updates)
    return redirect(url_for('camera.camera_manager'))

@camera_bp.route('/delete-camera-settings/<setting_name>', methods=['POST'])
def delete_camera_settings(setting_name):
    from sqlite.camera_settings_sqlite_provider import camera_settings_provider
    camera_settings_provider.delete_settings(setting_name)
    return redirect(url_for('camera.camera_manager'))