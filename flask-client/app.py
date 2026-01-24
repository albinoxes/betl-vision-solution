from flask import Flask, render_template
from controllers.camera_controller import camera_bp
from controllers.ml_model_controller import ml_bp

app = Flask(__name__)

app.register_blueprint(camera_bp)
app.register_blueprint(ml_bp)

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
