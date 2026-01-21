import time
import sys
import io
from PIL import Image
import visiontransfer
from flask import Flask, Response

app = Flask(__name__)

def connect_device():
    device_enum = visiontransfer.DeviceEnumeration()
    devices = device_enum.discover_devices()
    if len(devices) < 1:
        print('No devices found')
        sys.exit(1)

    print('Found these devices:')
    for i, info in enumerate(devices):
        print(f'  {i+1}: {info}')
    selected_device = 0 if len(devices)==1 else (int(input('Device to open: ') or '1')-1)
    device = devices[selected_device]

    try:
        transfer = visiontransfer.AsyncTransfer(device)
        print('Successfully connected to the device.')
        return transfer
    except Exception as e:
        print('Failed to connect to the device.')
        print('Error:', e)
        return None

def generate_video_stream():
    transfer = connect_device()
    if transfer is None:
        return
    while True:
        try:
            image_set = transfer.collect_received_image_set()
            if image_set is None:
                print('No image captured. Attempting to reconnect...')
                transfer = connect_device()
                continue
            img2d = image_set.get_pixel_data(0, force8bit=True)  # assuming left channel is channel 0
            # Encode the image as JPEG using PIL
            img = Image.fromarray(img2d)
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG')
            frame = buffer.getvalue()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        except Exception as e:
            print('Failed to capture image.')
            print('Error:', e)
            print('Attempting to reconnect...')
            transfer = connect_device()
            continue

@app.route('/camera-video')
def video():
    return Response(generate_video_stream(),
                mimetype="multipart/x-mixed-replace; boundary=frame")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002)