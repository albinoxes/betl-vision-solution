import time
import sys
import io
from PIL import Image
import visiontransfer
from flask import Flask, Response, jsonify
import signal
import threading
from collections import defaultdict
import queue

app = Flask(__name__)

# Track active camera connections and shared streams
active_cameras = set()
camera_lock = threading.Lock()

# Shared frame queues for each camera
# Structure: {device_id: {'frame': latest_frame, 'subscribers': set(), 'thread': thread_obj}}
shared_streams = {}
streams_lock = threading.Lock()

# Graceful shutdown handler
def signal_handler(sig, frame):
    print('\nShutdown signal received. Cleaning up...')
    # Stop all stream threads
    with streams_lock:
        for device_id, stream_info in shared_streams.items():
            stream_info['running'] = False
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

def connect_device(device_id):
    device_enum = visiontransfer.DeviceEnumeration()
    devices = device_enum.discover_devices()
    if len(devices) < 1 or device_id >= len(devices):
        print('No devices found or invalid device ID')
        return None

    device = devices[device_id]

    try:
        transfer = visiontransfer.AsyncTransfer(device)
        print(f'Successfully connected to device {device_id}.')
        return transfer
    except Exception as e:
        print('Failed to connect to the device.')
        print('Error:', e)
        return None

def camera_capture_thread(device_id):
    """Background thread that continuously captures frames from a camera"""
    transfer = connect_device(device_id)
    if transfer is None:
        return
    
    print(f'Camera capture thread started for device {device_id}')
    
    # FPS limiting
    target_fps = 30
    frame_delay = 1.0 / target_fps
    last_frame_time = 0
    
    try:
        while True:
            with streams_lock:
                if device_id not in shared_streams or not shared_streams[device_id].get('running', False):
                    break
            
            # Throttle frame rate
            current_time = time.time()
            if current_time - last_frame_time < frame_delay:
                time.sleep(frame_delay - (current_time - last_frame_time))
            
            try:
                image_set = transfer.collect_received_image_set()
                if image_set is None:
                    print('No image captured. Attempting to reconnect...')
                    transfer = connect_device(device_id)
                    continue
                
                img2d = image_set.get_pixel_data(0, force8bit=True)
                img = Image.fromarray(img2d)
                buffer = io.BytesIO()
                img.save(buffer, format='JPEG', quality=85)
                frame = buffer.getvalue()
                
                # Update shared frame
                with streams_lock:
                    if device_id in shared_streams:
                        shared_streams[device_id]['frame'] = frame
                        shared_streams[device_id]['last_update'] = time.time()
                
                last_frame_time = time.time()
                        
            except Exception as e:
                print(f'Error capturing frame from device {device_id}: {e}')
                time.sleep(0.1)
                continue
                
    finally:
        print(f'Camera capture thread stopped for device {device_id}')
        try:
            del transfer
        except:
            pass
        with streams_lock:
            if device_id in shared_streams:
                del shared_streams[device_id]
        with camera_lock:
            active_cameras.discard(device_id)

def generate_shared_stream(device_id):
    """Generate stream from shared frames for a specific client"""
    subscriber_id = id(threading.current_thread())
    
    # Start capture thread if not already running
    with streams_lock:
        if device_id not in shared_streams:
            shared_streams[device_id] = {
                'frame': None,
                'running': True,
                'last_update': time.time(),
                'subscribers': set()
            }
            # Start background capture thread
            capture_thread = threading.Thread(
                target=camera_capture_thread,
                args=(device_id,),
                daemon=True
            )
            shared_streams[device_id]['thread'] = capture_thread
            capture_thread.start()
            
            # Mark camera as active
            with camera_lock:
                active_cameras.add(device_id)
        
        shared_streams[device_id]['subscribers'].add(subscriber_id)
    
    try:
        last_frame = None
        while True:
            with streams_lock:
                if device_id not in shared_streams:
                    break
                frame = shared_streams[device_id].get('frame')
            
            if frame and frame != last_frame:
                last_frame = frame
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            else:
                # Wait a bit if no new frame
                time.sleep(0.03)  # ~30 FPS max
                
    except GeneratorExit:
        print(f'Client disconnected from device {device_id}')
    finally:
        # Remove this subscriber
        with streams_lock:
            if device_id in shared_streams:
                shared_streams[device_id]['subscribers'].discard(subscriber_id)
                # If no more subscribers, stop the capture thread
                if len(shared_streams[device_id]['subscribers']) == 0:
                    print(f'No more subscribers for device {device_id}, stopping capture thread')
                    shared_streams[device_id]['running'] = False
@app.route('/camera-video/<int:device_id>')
def video(device_id):
    return Response(generate_shared_stream(device_id),
                mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route('/devices')
def get_devices():
    """Return list of devices, showing active status if camera is in use"""
    device_enum = visiontransfer.DeviceEnumeration()
    devices = device_enum.discover_devices()
    device_list = []
    
    with camera_lock:
        active_set = active_cameras.copy()
    
    for i, info in enumerate(devices):
        device_list.append({
            'id': i,
            'info': str(info),
            'status': 'active' if i in active_set else 'available'
        })
    return jsonify(device_list)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002)