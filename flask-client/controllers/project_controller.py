from flask import Blueprint, jsonify, request, render_template
from sqlite.project_settings_sqlite_provider import ProjectSettingsSQLiteProvider

project_bp = Blueprint('project', __name__)
provider = ProjectSettingsSQLiteProvider()


@project_bp.route('/project-settings-page')
def project_settings():
    """
    Render the project settings page.
    """
    from sqlite.ml_sqlite_provider import ml_provider
    from sqlite.camera_settings_sqlite_provider import camera_settings_provider
    models = ml_provider.list_models()
    classifiers = ml_provider.list_classifiers()
    camera_settings = camera_settings_provider.list_settings()
    return render_template('project-settings.html', models=models, classifiers=classifiers, camera_settings=camera_settings)


@project_bp.route('/project-settings', methods=['GET'])
def get_project_settings():
    """
    Get the current project settings.
    """
    settings = provider.get_settings_dict()
    if settings:
        return jsonify(settings)
    return jsonify({'error': 'No settings found'}), 404


@project_bp.route('/project-settings', methods=['POST'])
def update_project_settings():
    """
    Update project settings.
    Expects JSON: { "vm_number": "...", "title": "...", "description": "...", "iris_main_folder": "...", "iris_classifier_subfolder": "...", "iris_model_subfolder": "...", "csv_interval_seconds": 60, "image_processing_interval": 1.0 }
    """
    data = request.get_json()
    
    vm_number = data.get('vm_number', '').strip()
    title = data.get('title', '').strip()
    description = data.get('description', '').strip()
    iris_main_folder = data.get('iris_main_folder', '').strip()
    iris_classifier_subfolder = data.get('iris_classifier_subfolder', '').strip()
    iris_model_subfolder = data.get('iris_model_subfolder', '').strip()
    csv_interval_seconds = int(data.get('csv_interval_seconds', 60))
    image_processing_interval = float(data.get('image_processing_interval', 1.0))
    
    if not vm_number or not title:
        return jsonify({'error': 'vm_number and title are required'}), 400
    
    success = provider.update_settings(vm_number, title, description, 
                                      iris_main_folder, iris_classifier_subfolder, 
                                      iris_model_subfolder, csv_interval_seconds, 
                                      image_processing_interval)
    
    if success:
        return jsonify({'message': 'Settings updated successfully', 'settings': provider.get_settings_dict()})
    return jsonify({'error': 'Failed to update settings'}), 500
