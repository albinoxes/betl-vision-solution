from flask import Blueprint, jsonify, request, render_template
from sqlite.project_settings_sqlite_provider import ProjectSettingsSQLiteProvider

project_bp = Blueprint('project', __name__)
provider = ProjectSettingsSQLiteProvider()


@project_bp.route('/project-settings-page')
def project_settings():
    """
    Render the project settings page.
    """
    return render_template('project-settings.html')


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
    Expects JSON: { "vm_number": "...", "title": "...", "description": "..." }
    """
    data = request.get_json()
    
    vm_number = data.get('vm_number', '').strip()
    title = data.get('title', '').strip()
    description = data.get('description', '').strip()
    
    if not vm_number or not title:
        return jsonify({'error': 'vm_number and title are required'}), 400
    
    success = provider.update_settings(vm_number, title, description)
    
    if success:
        return jsonify({'message': 'Settings updated successfully', 'settings': provider.get_settings_dict()})
    return jsonify({'error': 'Failed to update settings'}), 500
