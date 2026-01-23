import cv2
from sqlite.camera_settings_sqlite_provider import camera_settings_provider
from sqlite.ml_sqlite_provider import ml_provider


def get_model_from_database(model_id=None):
    """
    Get ML model from the database.
    If model_id is None, returns the first available model.
    
    Args:
        model_id: String in format "name:version" or None for first available model
    
    Returns:
        Loaded model object or None
    """
    if model_id is not None:
        # Parse model_id as "name:version"
        if ':' in model_id:
            name, version = model_id.split(':', 1)
        else:
            name = model_id
            version = '1.0.0'
        model = ml_provider.load_ml_model(name, version)
    else:
        # Get first available model
        all_models = ml_provider.list_models()
        if not all_models:
            return None
        # Use first model: (id, name, version, model_type, description, created_at, updated_at)
        first_model = all_models[0]
        model = ml_provider.load_ml_model(first_model[1], first_model[2])
    
    return model


def get_camera_settings(settings_id=None):
    """
    Get camera settings from the database.
    If settings_id is None, returns the first available settings.
    """
    if settings_id is not None:
        # Get by name or id - assuming name is used as identifier
        settings = camera_settings_provider.get_settings(settings_id)
    else:
        # Get first available settings
        all_settings = camera_settings_provider.list_settings()
        if not all_settings:
            # Return default values if no settings exist
            return {
                'min_conf': 0.8,
                'pixels_per_mm': 1 / (900 / 240),
                'particle_bb_dimension_factor': 0.9,
                'est_particle_volume_x': 8.357470139e-11,
                'est_particle_volume_exp': 3.02511466443
            }
        settings = all_settings[0]
    
    # Parse settings tuple: (id, name, min_conf, min_d_detect, min_d_save, particle_bb_dimension_factor, est_particle_volume_x, est_particle_volume_exp, created_at, updated_at)
    pixels_per_mm = 1 / (900 / 240)  # This is calculated, not stored in DB
    
    return {
        'min_conf': settings[2],
        'pixels_per_mm': pixels_per_mm,
        'particle_bb_dimension_factor': settings[5],
        'est_particle_volume_x': settings[6],
        'est_particle_volume_exp': settings[7]
    }


# Run boulder detection model
def object_process_image(img2d, model_id=None, settings_id=None):
    # Get model from database
    model = get_model_from_database(model_id)
    if model is None:
        raise ValueError("No model found in database")
    
    # Get settings from database
    settings = get_camera_settings(settings_id)
    min_conf = settings['min_conf']
    pixels_per_mm = settings['pixels_per_mm']
    particle_bb_dimension_factor = settings['particle_bb_dimension_factor']
    est_particle_volume_x = settings['est_particle_volume_x']
    est_particle_volume_exp = settings['est_particle_volume_exp']
    
    # Convert RGBA image to RGB
    img2d = cv2.cvtColor(img2d, cv2.COLOR_RGBA2RGB)
    
    # Boulder Detection Model and Calculate Parameters - belt class excluded
    results = model.predict(img2d, conf=min_conf, classes=1, show_boxes=True)
    image = results[0].path
    xyxy = results[0].boxes.xyxy.tolist()
    width = [(box[2] - box[0]) for box in xyxy]  # calculate width
    height = [(box[3] - box[1]) for box in xyxy]  # calculate height
    conf = [float(c) for c in results[0].boxes.conf.tolist()]  # convert each confidence score to a decimal
    width_px = [int(box[2] - box[0]) for box in xyxy]  # width in pixels
    height_px = [int(box[3] - box[1]) for box in xyxy]  # height in pixels
    width_mm = [int(w / pixels_per_mm) for w in width]  # calculate width in mm
    height_mm = [int(h / pixels_per_mm) for h in height]  # calculate height in mm

    # calculate max particle dimension (max_d_mm) and volume estimate per detected particle (vol_est)
    max_d_mm = [round(max(w, h) * particle_bb_dimension_factor) for w, h in zip(width_mm, height_mm)]
    volume_est = [est_particle_volume_x * (d ** est_particle_volume_exp) for d in max_d_mm]

    # Prepare the result in a list
    result = [image, xyxy, conf, width_px, height_px, width_mm, height_mm, max_d_mm, volume_est]

    return result