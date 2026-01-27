import cv2
import time
from flask import Flask, Response, jsonify

app = Flask(__name__)

# Configuration
TARGET_FPS = 30  # Limit frame rate to reduce CPU usage

def gen_frames():
    """Generate video frames from webcam with FPS limiting and proper resource management."""
    camera = cv2.VideoCapture(0)  # Open camera per stream session
    
    try:
        if not camera.isOpened():
            print("Error: Could not open webcam")
            return
        
        frame_delay = 1.0 / TARGET_FPS  # Time between frames
        last_frame_time = 0
        
        while True:
            current_time = time.time()
            
            # Throttle frame rate
            if current_time - last_frame_time < frame_delay:
                time.sleep(frame_delay - (current_time - last_frame_time))
            
            success, frame = camera.read()
            if not success:
                print("Error: Failed to read frame from webcam")
                break
            
            _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            last_frame_time = time.time()
            
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" +
                   buffer.tobytes() + b"\r\n")
    
    finally:
        # Always release camera when stream ends
        camera.release()
        print("Webcam released")

@app.route("/video")
def webcam():
    return Response(gen_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/devices")
def get_devices():
    # Check if webcam is available
    test_camera = cv2.VideoCapture(0)
    available = test_camera.isOpened()
    test_camera.release()
    device_list = [{
        'id': 0,
        'info': 'Webcam (localhost)',
        'status': 'available' if available else 'not available'
    }]
    return jsonify(device_list)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
