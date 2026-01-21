from flask import Blueprint, render_template, Response, jsonify, request, redirect, url_for
import requests

CAMERA_URL = "http://localhost:5001/video"

def generate_frames():
    r = requests.get(CAMERA_URL, stream=True)
    return Response(r.iter_content(chunk_size=1024),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

camera_bp = Blueprint('camera', __name__)

@camera_bp.route('/video')
def video():
    return generate_frames()

@camera_bp.route('/legacy-camera-video/<int:device_id>')
def legacy_camera_video(device_id):
    url = f"http://localhost:5002/camera-video/{device_id}"
    r = requests.get(url, stream=True)
    return Response(r.iter_content(chunk_size=1024),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

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

@camera_bp.route('/model-manager')
def model_manager():
    from sqlite.ml_sqlite_provider import ml_provider
    models = ml_provider.list_models()
    return render_template('model-manager.html', models=models)

@camera_bp.route('/upload-model', methods=['POST'])
def upload_model():
    from sqlite.ml_sqlite_provider import ml_provider

    file = request.files.get('model_file')
    if not file:
        return "No file uploaded", 400

    name = request.form.get('name')
    version = request.form.get('version')
    model_type = request.form.get('model_type')
    description = request.form.get('description')

    if not all([name, version, model_type]):
        return "Missing required fields", 400

    data = file.read()
    try:
        ml_provider.insert_model(name, version, model_type, data, description)
        return redirect(url_for('camera.model_manager'))
    except Exception as e:
        return f"Error uploading model: {str(e)}", 500

@camera_bp.route('/camera-manager')
def camera_manager():
    return render_template('camera-manager.html')