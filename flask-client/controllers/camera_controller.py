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