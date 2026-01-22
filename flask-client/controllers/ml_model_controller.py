from flask import Blueprint, render_template, request, redirect, url_for

ml_bp = Blueprint('ml', __name__)

@ml_bp.route('/model-manager')
def model_manager():
    from sqlite.ml_sqlite_provider import ml_provider
    models = ml_provider.list_models()
    return render_template('model-manager.html', models=models)

@ml_bp.route('/upload-model', methods=['POST'])
def upload_model():
    from sqlite.ml_sqlite_provider import ml_provider

    file = request.files.get('model_file')
    if not file:
        return "No file uploaded", 400

    name = request.form.get('name')
    version = request.form.get('version')
    model_type = request.form.get('model_type')
    description = request.form.get('description')

    if not all([name, version, model_type]):
        return "Missing required fields", 400

    data = file.read()
    try:
        ml_provider.insert_model(name, version, model_type, data, description)
        return redirect(url_for('ml.model_manager'))
    except Exception as e:
        return f"Error uploading model: {str(e)}", 500