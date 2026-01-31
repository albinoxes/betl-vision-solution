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
    from controllers.camera_controller import active_threads, thread_lock
    
    logger.info("\nShutting down... stopping all active threads")
    
    with thread_lock:
        thread_ids = list(active_threads.keys())
    
    for thread_id in thread_ids:
        logger.info(f"Stopping thread: {thread_id}")
        
        with thread_lock:
            if thread_id in active_threads:
                active_threads[thread_id]['running'] = False
                active_threads[thread_id]['status'] = 'stopping'
                session_obj = active_threads[thread_id].get('session')
                thread_obj = active_threads[thread_id].get('thread')
        
        # Close session to interrupt blocking reads
        if session_obj:
            try:
                session_obj.close()
            except Exception as e:
                logger.error(f"Error closing session for {thread_id}: {e}")
        
        # Wait for thread to stop
        if thread_obj and thread_obj.is_alive():
            thread_obj.join(timeout=2)
            if thread_obj.is_alive():
                logger.warning(f"Warning: Thread {thread_id} did not stop gracefully")
    
    logger.info("All threads stopped. Exiting...")
    
    # Stop health monitoring
    health_service.stop_all()
    
    # Stop logger
    logger.stop()

def signal_handler(sig, frame):
    """Handle Ctrl-C signal"""
    print("\n\nReceived interrupt signal, shutting down...")
    cleanup_threads()
    sys.exit(0)

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
