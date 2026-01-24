import cv2
import os
from flask import Flask, Response, jsonify

app = Flask(__name__)

# Path to the mock video file
MOCK_VIDEO_PATH = os.path.join(os.path.dirname(__file__), 'mock', 'test-video.avi')

def generate_video_stream():
    """Generate MJPEG stream from the mock video file."""
    while True:
        cap = cv2.VideoCapture(MOCK_VIDEO_PATH)
        if not cap.isOpened():
            print(f"Error: Could not open video file {MOCK_VIDEO_PATH}")
            break
        
        while True:
            ret, frame = cap.read()
            if not ret:
                # Loop the video by breaking and restarting
                break
            
            # Encode frame as JPEG
            _, buffer = cv2.imencode('.jpg', frame)
            frame_bytes = buffer.tobytes()
            
            # Yield frame in multipart format (same as legacy camera server)
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            
            # Add small delay to control frame rate
            cv2.waitKey(33)  # ~30 fps
        
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