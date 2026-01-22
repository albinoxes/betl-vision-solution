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
    models = ml_provider.list_models()
    classifiers = ml_provider.list_classifiers()
    return render_template('camera-manager.html', models=models, classifiers=classifiers)