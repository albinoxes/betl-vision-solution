import cv2
from flask import Flask, Response, jsonify

app = Flask(__name__)
camera = cv2.VideoCapture(0)

def gen_frames():
    while True:
        success, frame = camera.read()
        if not success:
            break
        _, buffer = cv2.imencode(".jpg", frame)
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" +
               buffer.tobytes() + b"\r\n")

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
