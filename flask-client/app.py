import requests
from flask import Flask, render_template, request, Response, jsonify
import sqlite3

app = Flask(__name__)

@app.route('/')
@app.route('/home')
def index():
    return render_template('index.html')

connect = sqlite3.connect('database.db')
connect.execute(
    'CREATE TABLE IF NOT EXISTS PARTICIPANTS (name TEXT, \
    email TEXT, city TEXT, country TEXT, phone TEXT)')

@app.route('/join', methods=['GET', 'POST'])
def join():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        city = request.form['city']
        country = request.form['country']
        phone = request.form['phone']
        with sqlite3.connect("database.db") as users:
            cursor = users.cursor()
            cursor.execute("INSERT INTO PARTICIPANTS \
            (name,email,city,country,phone) VALUES (?,?,?,?,?)",
                           (name, email, city, country, phone))
            users.commit()
        return render_template("index.html")
    else:
        return render_template('join.html')

@app.route('/participants')
def participants():
    connect = sqlite3.connect('database.db')
    cursor = connect.cursor()
    cursor.execute('SELECT * FROM PARTICIPANTS')

    data = cursor.fetchall()
    return render_template("participants.html", data=data)


CAMERA_URL = "http://localhost:5001/video"

def generate_frames():

    r = requests.get(CAMERA_URL, stream=True)
    return Response(r.iter_content(chunk_size=1024),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video')
def video():
    return generate_frames()

@app.route('/legacy-camera-video/<int:device_id>')
def legacy_camera_video(device_id):
    url = f"http://localhost:5002/camera-video/{device_id}"
    r = requests.get(url, stream=True)
    return Response(r.iter_content(chunk_size=1024),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/connected-devices')
def connected_devices():
    devices = []
    try:
        # Query legacy-camera-server
        legacy_response = requests.get('http://localhost:5002/devices', timeout=5)
        if legacy_response.status_code == 200:
            legacy_devices = legacy_response.json()
            for dev in legacy_devices:
                devices.append({
                    'type': 'legacy',
                    'id': dev['id'],
                    'info': dev['info'],
                    'ip': dev['info'].split(';')[0] if ';' in dev['info'] else 'unknown',
                    'status': dev['status']
                })
    except:
        pass  # Server not running or error

    try:
        # Query webcam-server
        webcam_response = requests.get('http://localhost:5001/devices', timeout=5)
        if webcam_response.status_code == 200:
            webcam_devices = webcam_response.json()
            for dev in webcam_devices:
                devices.append({
                    'type': 'webcam',
                    'id': dev['id'],
                    'info': dev['info'],
                    'ip': 'localhost',
                    'status': dev['status']
                })
    except:
        pass

    return jsonify(devices)

@app.route('/camera-manager')
def camera_manager():
    return render_template('camera-manager.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
