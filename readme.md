- generate the environment for each:
    - python -m venv venv
    - activate it
    - add the dependencies

1) flask-client
    - python3.12 -m venv flask_env
    - .\flask_env\Scripts\Activate.ps1
    - pip install requests, flask, Pillow, opencv-python, torch, torchvision, ultralytics, pandas

2) webcam-server:
    - python3.12 -m venv webcam_env
    - .\webcam_env\Scripts\Activate.ps1
    - pip install opencv-python, flask

3) legacy-camera-server:
    - python3.12 -m venv legacy_camera_env
    - .\legacy_camera_env\Scripts\Activate.ps1
    - pip install .\legacy-camera-server\wheel\visiontransfer-10.6.0-cp312-cp312-win_amd64.whl
    - pip install flask
    - pip install "numpy<2.0"
    - pip install Pillow

4) simulator-server:
    - python3.12 -m venv simulator_env
    - .\simulator_env\Scripts\Activate.ps1
    - pip install opencv-python, flask