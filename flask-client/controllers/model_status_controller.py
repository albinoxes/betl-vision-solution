from flask import Blueprint, jsonify, request
from sqlite.model_status_sqlite_provider import model_status_provider

model_status_bp = Blueprint('model_status', __name__)


@model_status_bp.route('/model-statuses', methods=['GET'])
def get_all_statuses():
    statuses = model_status_provider.get_all_statuses()
    return jsonify([status.to_dict() for status in statuses])


@model_status_bp.route('/model-status/<int:status_id>', methods=['GET'])
def get_status(status_id):
    status = model_status_provider.get_status_by_id(status_id)
    if status:
        return jsonify(status.to_dict())
    return jsonify({'error': 'Status not found'}), 404


@model_status_bp.route('/model-status', methods=['POST'])
def create_status():
    data = request.get_json()
    
    status_id = data.get('id')
    name = data.get('name', '').strip()
    
    if status_id is None or not name:
        return jsonify({'error': 'id and name are required'}), 400
    
    try:
        status_id = int(status_id)
    except ValueError:
        return jsonify({'error': 'id must be an integer'}), 400
    
    success = model_status_provider.insert_status(status_id, name)
    
    if success:
        return jsonify({'message': 'Status created successfully', 'id': status_id}), 201
    return jsonify({'error': 'Failed to create status. ID might already exist.'}), 400


@model_status_bp.route('/model-status/<int:old_id>', methods=['PUT'])
def update_status(old_id):
    data = request.get_json()
    
    new_id = data.get('id')
    name = data.get('name', '').strip()
    
    if new_id is None or not name:
        return jsonify({'error': 'id and name are required'}), 400
    
    try:
        new_id = int(new_id)
    except ValueError:
        return jsonify({'error': 'id must be an integer'}), 400
    
    success = model_status_provider.update_status(old_id, new_id, name)
    
    if success:
        return jsonify({'message': 'Status updated successfully'})
    return jsonify({'error': 'Failed to update status'}), 400


@model_status_bp.route('/model-status/<int:status_id>', methods=['DELETE'])
def delete_status(status_id):
    success = model_status_provider.delete_status(status_id)
    
    if success:
        return jsonify({'message': 'Status deleted successfully'})
    return jsonify({'error': 'Status not found'}), 404


@model_status_bp.route('/model-statuses', methods=['DELETE'])
def delete_all_statuses():
    count = model_status_provider.delete_all_statuses()
    return jsonify({'message': f'{count} statuses deleted successfully'})
