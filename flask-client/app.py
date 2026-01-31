from flask import Flask, render_template
from controllers.camera_controller import camera_bp
from controllers.ml_model_controller import ml_bp
from controllers.project_controller import project_bp
from controllers.model_status_controller import model_status_bp
from controllers.sftp_controller import sftp_bp
from controllers.detection_model_settings_controller import detection_model_settings_bp
from infrastructure.logging.logging_provider import get_logger
import signal
import sys
import atexit

app = Flask(__name__)

# Initialize logging provider
logger = get_logger()
logger.start()

app.register_blueprint(camera_bp)
app.register_blueprint(ml_bp)
app.register_blueprint(project_bp)
app.register_blueprint(model_status_bp)
app.register_blueprint(sftp_bp)
app.register_blueprint(detection_model_settings_bp)

@app.route('/')
def index():
    return render_template('index.html')

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
    logger.stop()

def signal_handler(sig, frame):
    """Handle Ctrl-C signal"""
    cleanup_threads()
    sys.exit(0)

# Register cleanup on exit
atexit.register(lambda: logger.stop())

if __name__ == '__main__':
    # Register signal handler for Ctrl-C
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        app.run(host='0.0.0.0', port=5000, threaded=True)
    except KeyboardInterrupt:
        cleanup_threads()
        sys.exit(0)
