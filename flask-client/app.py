from flask import Flask, redirect, url_for
from controllers.camera_controller import camera_bp
from controllers.ml_model_controller import ml_bp

app = Flask(__name__)

app.register_blueprint(camera_bp)
app.register_blueprint(ml_bp)

@app.route('/')
def index():
    return redirect(url_for('camera.camera_manager'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
