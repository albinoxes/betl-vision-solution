from flask import Blueprint, request, redirect, url_for
import time

detection_model_settings_bp = Blueprint('detection_model_settings', __name__)

@detection_model_settings_bp.route('/add-camera-settings', methods=['POST'])
def add_camera_settings():
    from sqlite.detection_model_settings_sqlite_provider import detection_model_settings_provider

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
    
    detection_model_settings_provider.insert_settings(
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
    return redirect(url_for('project.project_settings') + '#ml-models')

@detection_model_settings_bp.route('/update-camera-settings/<setting_name>', methods=['POST'])
def update_camera_settings(setting_name):
    from sqlite.detection_model_settings_sqlite_provider import detection_model_settings_provider

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

    detection_model_settings_provider.update_settings(setting_name, **updates)
    # Add timestamp to force cache refresh
    return redirect(url_for('project.project_settings') + f'?t={int(time.time())}#ml-models')

@detection_model_settings_bp.route('/delete-camera-settings/<setting_name>', methods=['POST'])
def delete_camera_settings(setting_name):
    from sqlite.detection_model_settings_sqlite_provider import detection_model_settings_provider
    detection_model_settings_provider.delete_settings(setting_name)
    return redirect(url_for('project.project_settings') + '#ml-models')
