from flask import Flask, render_template
from controllers.camera_controller import camera_bp
from controllers.ml_model_controller import ml_bp
from controllers.project_controller import project_bp
from controllers.model_status_controller import model_status_bp
from controllers.sftp_controller import sftp_bp
from controllers.detection_model_settings_controller import detection_model_settings_bp
from controllers.health_controller import health_bp
from infrastructure.logging.logging_provider import get_logger
from infrastructure.monitoring import HealthMonitoringService, ServerConfig
import signal
import sys
import atexit

app = Flask(__name__)

# Initialize logging provider
logger = get_logger()
logger.start()

# Initialize health monitoring service
health_service = HealthMonitoringService()

# Register servers for health monitoring
health_service.register_server(ServerConfig(
    name="webcam-server",
    url="http://localhost",
    port=5001,
    health_endpoint="/devices",
    check_interval=5.0,
    timeout=2.0
))

health_service.register_server(ServerConfig(
    name="legacy-camera-server",
    url="http://localhost",
    port=5002,
    health_endpoint="/devices",
    check_interval=5.0,
    timeout=2.0
))

health_service.register_server(ServerConfig(
    name="simulator-server",
    url="http://localhost",
    port=5003,
    health_endpoint="/devices",
    check_interval=5.0,
    timeout=2.0
))

# Start health monitoring
health_service.start_all()

# Store health service in app config for access by controllers
app.config['HEALTH_SERVICE'] = health_service

app.register_blueprint(camera_bp)
app.register_blueprint(ml_bp)
app.register_blueprint(project_bp)
app.register_blueprint(model_status_bp)
app.register_blueprint(sftp_bp)
app.register_blueprint(health_bp)
app.register_blueprint(detection_model_settings_bp)

@app.route('/')
def index():
    # Get server health statuses
    server_statuses = health_service.get_all_statuses()
    servers = [
        {
            'name': name,
            'status': status.value,
            'available': status.value == 'available'
        }
        for name, status in server_statuses.items()
    ]
    return render_template('index.html', servers=servers)

def cleanup_threads():
    """Stop all active threads gracefully"""
    from infrastructure.thread_manager import get_thread_manager
    from infrastructure.socket_manager import get_socket_manager
    import gc
    
    logger.info("\nShutting down... stopping all active threads")
    
    thread_manager = get_thread_manager()
    thread_manager.stop_all_threads(timeout=10.0)  # Increased timeout
    
    logger.info("All threads stopped. Cleaning up resources...")
    
    # Close all socket connections
    socket_manager = get_socket_manager()
    socket_manager.shutdown()
    logger.info("All socket connections closed")
    
    # Stop health monitoring
    health_service.stop_all()
    
    # Force garbage collection to free memory
    collected = gc.collect()
    logger.info(f"Garbage collection freed {collected} objects")
    
    # Stop logger
    logger.stop()
    
    logger.info("Cleanup complete. Safe to exit.")

def signal_handler(sig, frame):
    """Handle Ctrl-C signal"""
    print("\n\nReceived interrupt signal, shutting down...")
    try:
        cleanup_threads()
    except Exception as e:
        print(f"Error during cleanup: {e}")
    finally:
        print("Forcing exit...")
        import os
        os._exit(0)  # Force exit without waiting for cleanup

# Register signal handler for Ctrl-C BEFORE starting Flask
signal.signal(signal.SIGINT, signal_handler)

# Register cleanup on exit
def cleanup_on_exit():
    try:
        health_service.stop_all()
        logger.stop()
    except:
        pass

atexit.register(cleanup_on_exit)

if __name__ == '__main__':
    try:
        # Don't use Flask's threaded mode, it interferes with signal handling
        # use_reloader=False prevents the app from starting twice
        app.run(host='0.0.0.0', port=5000, threaded=True, use_reloader=False)
    except (KeyboardInterrupt, SystemExit):
        print("\nShutdown initiated...")
        cleanup_threads()
    finally:
        print("Application stopped.")
