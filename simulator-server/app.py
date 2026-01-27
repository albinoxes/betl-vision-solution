import cv2
import os
import time
from flask import Flask, Response, jsonify

app = Flask(__name__)

# Path to the mock video file
MOCK_VIDEO_PATH = os.path.join(os.path.dirname(__file__), 'mock', 'test-video.avi')

# Configuration
TARGET_FPS = 30  # Limit frame rate to reduce CPU usage

def generate_video_stream():
    """Generate MJPEG stream from the mock video file with FPS limiting."""
    frame_delay = 1.0 / TARGET_FPS  # Time between frames
    
    while True:
        cap = cv2.VideoCapture(MOCK_VIDEO_PATH)
        if not cap.isOpened():
            print(f"Error: Could not open video file {MOCK_VIDEO_PATH}")
            break
        
        try:
            last_frame_time = 0
            
            while True:
                current_time = time.time()
                
                # Throttle frame rate
                if current_time - last_frame_time < frame_delay:
                    time.sleep(frame_delay - (current_time - last_frame_time))
                
                ret, frame = cap.read()
                if not ret:
                    # Loop the video by breaking and restarting
                    break
                
                # Encode frame as JPEG with quality setting
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                frame_bytes = buffer.tobytes()
                
                last_frame_time = time.time()
                
                # Yield frame in multipart format (same as legacy camera server)
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        
        finally:
            cap.release()

@app.route('/video/simulator')
def video_simulator():
    """Endpoint to stream the simulator video."""
    return Response(generate_video_stream(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/devices')
def get_devices():
    """Endpoint to report the simulator as a connected device."""
    device_list = [{
        'id': 0,
        'info': 'Simulator Device;Mock Video Stream;test-video.avi',
        'status': 'connected'
    }]
    return jsonify(device_list)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003)