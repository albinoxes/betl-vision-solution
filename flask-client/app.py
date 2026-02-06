from flask import Flask, render_template
from flask_cors import CORS
from controllers.camera_controller import camera_bp
from controllers.ml_model_controller import ml_bp
from controllers.project_controller import project_bp
from controllers.model_status_controller import model_status_bp
from controllers.sftp_controller import sftp_bp
from controllers.detection_model_settings_controller import detection_model_settings_bp
from controllers.health_controller import health_bp
from infrastructure.logging.logging_provider import get_logger
from infrastructure.monitoring import HealthMonitoringService, ServerConfig
from iris_communication.csv_writer_thread import get_csv_writer
from iris_communication.sftp_uploader_thread import get_sftp_uploader
from computer_vision.classifier_processor_thread import get_classifier_processor
from computer_vision.model_detector_thread import get_model_detector
import signal
import atexit

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Initialize logging provider (auto-starts on first use)
logger = get_logger()

# Initialize and start CSV writer thread
csv_writer = get_csv_writer()
csv_writer.start()
logger.info("CSV writer thread started")

# Initialize and start model detector thread
model_detector = get_model_detector()
model_detector.start()
logger.info("Model detector thread started")

# Initialize and start classifier processor thread
classifier_processor = get_classifier_processor()
classifier_processor.start()
logger.info("Classifier processor thread started")

# Initialize and start SFTP uploader thread
sftp_uploader = get_sftp_uploader()
sftp_uploader.start()
logger.info("SFTP uploader thread started")

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
    
    # Stop camera processing threads first
    thread_manager = get_thread_manager()
    thread_manager.stop_all_threads(timeout=10.0)
    
    # Stop model detector thread (finishes pending detections)
    model_detector = get_model_detector()
    if model_detector.is_running():
        logger.info("Stopping model detector thread...")
        model_detector.stop(timeout=10.0)
        logger.info("Model detector thread stopped")
    
    # Stop classifier processor thread (finishes pending classifications)
    classifier_processor = get_classifier_processor()
    if classifier_processor.is_running():
        logger.info("Stopping classifier processor thread...")
        classifier_processor.stop(timeout=10.0)
        logger.info("Classifier processor thread stopped")
    
    # Stop CSV writer thread (finishes pending CSV generations)
    csv_writer = get_csv_writer()
    if csv_writer.is_running():
        logger.info("Stopping CSV writer thread...")
        csv_writer.stop(timeout=10.0)
        logger.info("CSV writer thread stopped")
    
    # Stop SFTP uploader thread last (uploads any remaining CSVs)
    sftp_uploader = get_sftp_uploader()
    if sftp_uploader.is_running():
        logger.info("Stopping SFTP uploader thread...")
        sftp_uploader.stop(timeout=15.0)  # Give extra time for remaining uploads
        logger.info("SFTP uploader thread stopped")
    
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
    
    logger.info("Cleanup complete. Safe to exit.")
    
    # Stop logger (this flushes remaining logs and closes handlers)
    logger.stop()

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
        # Stop model detector
        model_detector = get_model_detector()
        if model_detector.is_running():
            model_detector.stop(timeout=5.0)
        # Stop classifier processor
        classifier_processor = get_classifier_processor()
        if classifier_processor.is_running():
            classifier_processor.stop(timeout=5.0)
        # Stop CSV writer
        csv_writer = get_csv_writer()
        if csv_writer.is_running():
            csv_writer.stop(timeout=5.0)
        # Stop SFTP uploader
        sftp_uploader = get_sftp_uploader()
        if sftp_uploader.is_running():
            sftp_uploader.stop(timeout=5.0)
        # Stop health service and logger
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
