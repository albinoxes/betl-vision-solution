import cv2
from sqlite.camera_settings_sqlite_provider import camera_settings_provider
from sqlite.ml_sqlite_provider import ml_provider


class DetectedParticle:
    """Represents a detected particle with its measurements and properties."""
    
    def __init__(self, conf, width_px, height_px, width_mm, height_mm, max_d_mm, volume_est):
        self.conf = conf
        self.width_px = width_px
        self.height_px = height_px
        self.width_mm = width_mm
        self.height_mm = height_mm
        self.max_d_mm = max_d_mm
        self.volume_est = volume_est
    
    def __repr__(self):
        return (f"DetectedParticle(conf={self.conf:.2f}, "
                f"width_px={self.width_px}, height_px={self.height_px}, "
                f"width_mm={self.width_mm}, height_mm={self.height_mm}, "
                f"max_d_mm={self.max_d_mm}, volume_est={self.volume_est:.2e})")


class CameraSettings:
    """Represents camera settings for particle detection."""
    
    def __init__(self, min_conf, pixels_per_mm, particle_bb_dimension_factor, est_particle_volume_x, est_particle_volume_exp):
        self.min_conf = min_conf
        self.pixels_per_mm = pixels_per_mm
        self.particle_bb_dimension_factor = particle_bb_dimension_factor
        self.est_particle_volume_x = est_particle_volume_x
        self.est_particle_volume_exp = est_particle_volume_exp
    
    def __repr__(self):
        return (f"CameraSettings(min_conf={self.min_conf}, "
                f"pixels_per_mm={self.pixels_per_mm:.4f}, "
                f"particle_bb_dimension_factor={self.particle_bb_dimension_factor}, "
                f"est_particle_volume_x={self.est_particle_volume_x:.2e}, "
                f"est_particle_volume_exp={self.est_particle_volume_exp})")


def get_model_from_database(model_id=None):
    model = None
    
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
        if all_models and len(all_models) > 0:
            # Use first model: (id, name, version, model_type, description, created_at, updated_at)
            first_model = all_models[0]
            if len(first_model) >= 3:
                model = ml_provider.load_ml_model(first_model[1], first_model[2])
    
    return model


def get_camera_settings(settings_id=None):
    settings = None
    if settings_id is not None:
        # Get by name or id - assuming name is used as identifier
        settings = camera_settings_provider.get_settings(settings_id)
    else:
        # Get first available settings
        all_settings = camera_settings_provider.list_settings()
        if all_settings:
            settings = all_settings[0]
    
    # Return default values if no settings found
    if settings is None:
        return CameraSettings(
            min_conf=0.8,
            pixels_per_mm=1 / (900 / 240),
            particle_bb_dimension_factor=0.9,
            est_particle_volume_x=8.357470139e-11,
            est_particle_volume_exp=3.02511466443
        )
    
    # Parse settings tuple: (id, name, min_conf, min_d_detect, min_d_save, particle_bb_dimension_factor, est_particle_volume_x, est_particle_volume_exp, created_at, updated_at)
    pixels_per_mm = 1 / (900 / 240)  # This is calculated, not stored in DB
    
    return CameraSettings(
        min_conf=settings[2],
        pixels_per_mm=pixels_per_mm,
        particle_bb_dimension_factor=settings[5],
        est_particle_volume_x=settings[6],
        est_particle_volume_exp=settings[7]
    )


# Run boulder detection model
def object_process_image(img2d, model=None, model_id=None, settings=None, settings_id=None):
    # Get model from database if not provided
    if model is None:
        model = get_model_from_database(model_id)
        if model is None:
            raise ValueError("No model found in database")
    
    # Get settings from database if not provided
    if settings is None:
        settings = get_camera_settings(settings_id)
    
    # Convert RGBA image to RGB
    img2d = cv2.cvtColor(img2d, cv2.COLOR_RGBA2RGB)
    
    # Boulder Detection Model and Calculate Parameters - belt class excluded
    results = model.predict(img2d, conf=settings.min_conf, classes=1, show_boxes=True)
    image = results[0].path
    xyxy = results[0].boxes.xyxy.tolist()
    width = [(box[2] - box[0]) for box in xyxy]  # calculate width
    height = [(box[3] - box[1]) for box in xyxy]  # calculate height
    conf = [float(c) for c in results[0].boxes.conf.tolist()]  # convert each confidence score to a decimal
    width_px = [int(box[2] - box[0]) for box in xyxy]  # width in pixels
    height_px = [int(box[3] - box[1]) for box in xyxy]  # height in pixels
    width_mm = [int(w / settings.pixels_per_mm) for w in width]  # calculate width in mm
    height_mm = [int(h / settings.pixels_per_mm) for h in height]  # calculate height in mm

    # calculate max particle dimension (max_d_mm) and volume estimate per detected particle (vol_est)
    max_d_mm = [round(max(w, h) * settings.particle_bb_dimension_factor) for w, h in zip(width_mm, height_mm)]
    volume_est = [settings.est_particle_volume_x * (d ** settings.est_particle_volume_exp) for d in max_d_mm]

    # Create DetectedParticle instances for each detected object
    particles = [
        DetectedParticle(
            conf=c,
            width_px=wp,
            height_px=hp,
            width_mm=wm,
            height_mm=hm,
            max_d_mm=md,
            volume_est=ve
        )
        for c, wp, hp, wm, hm, md, ve in zip(conf, width_px, height_px, width_mm, height_mm, max_d_mm, volume_est)
    ]

    # Prepare the result with image, bounding boxes, and particle objects
    result = [image, xyxy, particles]

    return result