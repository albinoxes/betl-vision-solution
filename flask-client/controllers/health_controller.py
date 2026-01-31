"""
Health monitoring controller for server status endpoints.
"""

from flask import Blueprint, jsonify, current_app
from infrastructure.monitoring import HealthMonitoringService

health_bp = Blueprint('health', __name__)


@health_bp.route('/health/servers')
def get_servers_health():
    """
    Get health status of all monitored servers.
    
    Returns:
        JSON object with server statuses
    """
    health_service = current_app.config['HEALTH_SERVICE']
    
    statuses = health_service.get_all_statuses()
    
    return jsonify({
        server_name: status.value
        for server_name, status in statuses.items()
    })


@health_bp.route('/health/servers/<server_name>')
def get_server_health(server_name):
    """
    Get health status of a specific server.
    
    Args:
        server_name: Name of the server to check
        
    Returns:
        JSON object with server status
    """
    health_service = current_app.config['HEALTH_SERVICE']
    
    status = health_service.get_server_status(server_name)
    
    if status is None:
        return jsonify({'error': f'Server {server_name} not found'}), 404
    
    return jsonify({
        'server': server_name,
        'status': status.value,
        'available': status.value == 'available'
    })
