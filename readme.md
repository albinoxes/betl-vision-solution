- generate the environment for each:
    - python -m venv venv
    - activate it
    - add the dependencies

1) flask-client
    - belt-vision-solution\flask-client> python -m venv flask_env
    - belt-vision-solution\flask-client> .\flask_env\Scripts\Activate.ps1
    - pip install requests, flask

2) webcam-server:
    - belt-vision-solution\webcam-server> python -m venv webcam_env
    - belt-vision-solution\webcam-server> .\webcam_env\Scripts\Activate.ps1
    - belt-vision-solution\webcam-server> pip install opencv-python, flask