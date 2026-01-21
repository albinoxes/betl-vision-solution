from flask import Flask
from controllers.camera_controller import camera_bp
from controllers.participants_controller import participants_bp

app = Flask(__name__)

app.register_blueprint(camera_bp)
app.register_blueprint(participants_bp)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
