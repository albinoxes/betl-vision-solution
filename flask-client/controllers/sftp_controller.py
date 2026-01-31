from flask import Blueprint, jsonify, request
from sqlite.sftp_sqlite_provider import sftp_provider

sftp_bp = Blueprint('sftp', __name__)


@sftp_bp.route('/sftp-servers', methods=['GET'])
def get_all_servers():
    """Get all SFTP server configurations."""
    servers = sftp_provider.get_all_servers()
    return jsonify([server.to_dict() for server in servers])


@sftp_bp.route('/sftp-server/<int:server_id>', methods=['GET'])
def get_server(server_id):
    """Get a specific SFTP server configuration by ID."""
    server = sftp_provider.get_server_by_id(server_id)
    if server:
        return jsonify(server.to_dict())
    return jsonify({'error': 'SFTP server not found'}), 404


@sftp_bp.route('/sftp-server', methods=['POST'])
def create_server():
    """Create a new SFTP server configuration."""
    data = request.get_json()
    
    server_name = data.get('server_name', '').strip()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    if not server_name or not username or not password:
        return jsonify({'error': 'server_name, username, and password are required'}), 400
    
    server_id = sftp_provider.insert_server(server_name, username, password)
    
    if server_id:
        return jsonify({'message': 'SFTP server created successfully', 'id': server_id}), 201
    return jsonify({'error': 'Failed to create SFTP server'}), 400


@sftp_bp.route('/sftp-server/<int:server_id>', methods=['PUT'])
def update_server(server_id):
    """Update an existing SFTP server configuration."""
    data = request.get_json()
    
    server_name = data.get('server_name', '').strip()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    if not server_name or not username or not password:
        return jsonify({'error': 'server_name, username, and password are required'}), 400
    
    success = sftp_provider.update_server(server_id, server_name, username, password)
    
    if success:
        return jsonify({'message': 'SFTP server updated successfully'})
    return jsonify({'error': 'Failed to update SFTP server'}), 400


@sftp_bp.route('/sftp-server/<int:server_id>', methods=['DELETE'])
def delete_server(server_id):
    """Delete an SFTP server configuration."""
    success = sftp_provider.delete_server(server_id)
    
    if success:
        return jsonify({'message': 'SFTP server deleted successfully'})
    return jsonify({'error': 'SFTP server not found'}), 404


@sftp_bp.route('/sftp-servers', methods=['DELETE'])
def delete_all_servers():
    """Delete all SFTP server configurations."""
    count = sftp_provider.delete_all_servers()
    return jsonify({'message': f'{count} SFTP servers deleted successfully'})
