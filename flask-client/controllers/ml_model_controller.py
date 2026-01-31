from flask import Blueprint, render_template, request, redirect, url_for

ml_bp = Blueprint('ml', __name__)

@ml_bp.route('/model-manager')
def model_manager():
    from sqlite.ml_sqlite_provider import ml_provider
    models = ml_provider.list_models()
    classifiers = ml_provider.list_classifiers()
    return render_template('model-manager.html', models=models, classifiers=classifiers)

@ml_bp.route('/upload-model', methods=['POST'])
def upload_model():
    from sqlite.ml_sqlite_provider import ml_provider

    file = request.files.get('model_file')
    if not file:
        return "No file uploaded", 400

    name = request.form.get('name')
    version = request.form.get('version')
    model_type = request.form.get('model_type')
    category = request.form.get('category', 'model')

    if not all([name, version, model_type]):
        return "Missing required fields", 400

    data = file.read()
    ml_provider.insert_model(name, version, model_type, data, category)
    return redirect(url_for('project.project_settings') + '#ml-models')

@ml_bp.route('/delete-model/<int:model_id>', methods=['POST'])
def delete_model(model_id):
    from sqlite.ml_sqlite_provider import ml_provider
    ml_provider.delete_model_by_id(model_id)
    return redirect(url_for('project.project_settings') + '#ml-models')