## @file ml_model_image_processor.py
#  @brief ML model image processor for object detection and particle analysis.
#
#  This module provides functionality for processing images with YOLO-based object detection models,
#  analyzing detected particles, and applying configurable camera settings for filtering and measurements.
#
#  @author Belt Vision Team
#  @date 2026

import cv2
from sqlite.detection_model_settings_sqlite_provider import detection_model_settings_provider
from sqlite.ml_sqlite_provider import ml_provider


class DetectedParticle:
    """@brief Represents a detected particle with its measurements and properties.
    
    This class encapsulates all the measurements and calculated properties of a particle
    detected by the object detection model, including pixel-based and real-world dimensions.
    """
    
    def __init__(self, conf, width_px, height_px, width_mm, height_mm, max_d_mm, volume_est):
        """@brief Initialize a DetectedParticle instance.
        
        @param conf Confidence score of the detection (0.0 to 1.0)
        @param width_px Width of the particle bounding box in pixels
        @param height_px Height of the particle bounding box in pixels
        @param width_mm Width of the particle in millimeters
        @param height_mm Height of the particle in millimeters
        @param max_d_mm Maximum dimension of the particle in millimeters (width or height)
        @param volume_est Estimated volume of the particle in cubic millimeters
        """
        self.conf = conf
        self.width_px = width_px
        self.height_px = height_px
        self.width_mm = width_mm
        self.height_mm = height_mm
        self.max_d_mm = max_d_mm
        self.volume_est = volume_est
    
    def __repr__(self):
        """@brief String representation of the DetectedParticle.
        
        @return String representation with all particle measurements
        """
        return (f"DetectedParticle(conf={self.conf:.2f}, "
                f"width_px={self.width_px}, height_px={self.height_px}, "
                f"width_mm={self.width_mm}, height_mm={self.height_mm}, "
                f"max_d_mm={self.max_d_mm}, volume_est={self.volume_est:.2e})")


class CameraSettings:
    """@brief Represents camera settings for particle detection.
    
    This class contains all configurable parameters for particle detection, including
    confidence thresholds, pixel-to-millimeter conversion, dimension filters, and
    volume estimation parameters.
    """
    
    def __init__(self, min_conf, pixels_per_mm, min_d_detect, min_d_save, max_d_detect, max_d_save, 
                 particle_bb_dimension_factor, est_particle_volume_x, est_particle_volume_exp):
        """@brief Initialize CameraSettings instance.
        
        @param min_conf Minimum confidence threshold for detections (0.0 to 1.0)
        @param pixels_per_mm Conversion factor from pixels to millimeters
        @param min_d_detect Minimum particle dimension (mm) to include in detection reports
        @param min_d_save Minimum particle dimension (mm) to save/store
        @param max_d_detect Maximum particle dimension (mm) to include in detection reports
        @param max_d_save Maximum particle dimension (mm) to save/store
        @param particle_bb_dimension_factor Factor to adjust bounding box dimensions (typically 0.9)
        @param est_particle_volume_x Coefficient for volume estimation formula
        @param est_particle_volume_exp Exponent for volume estimation formula (volume = x * d^exp)
        """
        self.min_conf = min_conf
        self.pixels_per_mm = pixels_per_mm
        self.min_d_detect = min_d_detect
        self.min_d_save = min_d_save
        self.max_d_detect = max_d_detect
        self.max_d_save = max_d_save
        self.particle_bb_dimension_factor = particle_bb_dimension_factor
        self.est_particle_volume_x = est_particle_volume_x
        self.est_particle_volume_exp = est_particle_volume_exp
    
    def __repr__(self):
        """@brief String representation of the CameraSettings.
        
        @return String representation with all camera settings
        """
        return (f"CameraSettings(min_conf={self.min_conf}, "
                f"pixels_per_mm={self.pixels_per_mm:.4f}, "
                f"min_d_detect={self.min_d_detect}, min_d_save={self.min_d_save}, "
                f"max_d_detect={self.max_d_detect}, max_d_save={self.max_d_save}, "
                f"particle_bb_dimension_factor={self.particle_bb_dimension_factor}, "
                f"est_particle_volume_x={self.est_particle_volume_x:.2e}, "
                f"est_particle_volume_exp={self.est_particle_volume_exp})")


def get_model_from_database(model_id=None):
    """@brief Load a machine learning model from the database.
    
    Retrieves a YOLO object detection model from the database. If a specific model_id
    is provided, loads that model. Otherwise, loads the first available model.
    
    @param model_id Optional model identifier in format "name:version" or just "name"
                    If None, loads the first available model from database
    
    @return Loaded YOLO model object, or None if no model found
    
    @note If model_id contains no version, defaults to version '1.0.0'
    
    @code
    # Load specific model
    model = get_model_from_database("yolov8:2.0.0")
    
    # Load first available model
    model = get_model_from_database()
    @endcode
    """
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
    """@brief Load camera settings from the database.
    
    Retrieves camera settings configuration from the database. If a specific settings_id
    is provided, loads those settings. Otherwise, loads the first available settings.
    Returns default settings if none are found in the database.
    
    @param settings_id Optional settings identifier (name or id)
                       If None, loads the first available settings from database
    
    @return CameraSettings object with loaded or default configuration
    
    @note Default settings are used if no settings are found in database:
          - min_conf: 0.8
          - pixels_per_mm: ~0.267 (calculated from 900/240)
          - min_d_detect: 200mm
          - min_d_save: 200mm
          - max_d_detect: 10000mm
          - max_d_save: 10000mm
          - particle_bb_dimension_factor: 0.9
          - est_particle_volume_x: 8.357470139e-11
          - est_particle_volume_exp: 3.02511466443
    
    @code
    # Load specific settings
    settings = get_camera_settings("high_precision")
    
    # Load first available or default settings
    settings = get_camera_settings()
    @endcode
    """
    settings = None
    if settings_id is not None:
        # Get by name or id - assuming name is used as identifier
        settings = detection_model_settings_provider.get_settings(settings_id)
    else:
        # Get first available settings
        all_settings = detection_model_settings_provider.list_settings()
        if all_settings:
            settings = all_settings[0]
    
    # Return default values if no settings found
    if settings is None:
        return CameraSettings(
            min_conf=0.8,
            pixels_per_mm=1 / (900 / 240),
            min_d_detect=200,
            min_d_save=200,
            max_d_detect=10000,
            max_d_save=10000,
            particle_bb_dimension_factor=0.9,
            est_particle_volume_x=8.357470139e-11,
            est_particle_volume_exp=3.02511466443
        )
    
    # Parse settings tuple: (id, name, min_conf, min_d_detect, min_d_save, max_d_detect, max_d_save, particle_bb_dimension_factor, est_particle_volume_x, est_particle_volume_exp, created_at, updated_at)
    pixels_per_mm = 1 / (900 / 240)  # This is calculated, not stored in DB
    
    return CameraSettings(
        min_conf=settings[2],
        pixels_per_mm=pixels_per_mm,
        min_d_detect=settings[3],
        min_d_save=settings[4],
        max_d_detect=settings[5],
        max_d_save=settings[6],
        particle_bb_dimension_factor=settings[7],
        est_particle_volume_x=settings[8],
        est_particle_volume_exp=settings[9]
    )


def object_process_image(img2d, model=None, model_id=None, settings=None, settings_id=None):
    """@brief Process an image with the object detection model.
    
    Performs object detection on an input image using a YOLO model, calculates particle
    measurements in both pixels and millimeters, estimates volumes, and filters particles
    based on configured dimension ranges.
    
    The function supports two filtering modes:
    - Detection range (min_d_detect to max_d_detect): Particles to include in reports/CSV
    - Save range (min_d_save to max_d_save): Particles to save/store
    
    @param img2d Input image as numpy array (RGBA or RGB format)
    @param model Pre-loaded YOLO model (optional, will load from DB if not provided)
    @param model_id Model identifier to load from database if model not provided
    @param settings Pre-loaded CameraSettings object (optional, will load from DB if not provided)
    @param settings_id Settings identifier to load from database if settings not provided
    
    @return List containing [image_path, xyxy_boxes, particles_to_detect, particles_to_save]
            - image_path: Path to the processed image
            - xyxy_boxes: List of bounding boxes in [x1, y1, x2, y2] format
            - particles_to_detect: List of DetectedParticle objects within [min_d_detect, max_d_detect] range (for reporting/CSV)
            - particles_to_save: List of DetectedParticle objects within [min_d_save, max_d_save] range (for storage)
    
    @throws ValueError If no model is found in the database
    
    @note The function:
          1. Converts RGBA images to RGB
          2. Runs YOLO detection with configured confidence threshold
          3. Detects only class 1 (particles), excluding belt class
          4. Calculates dimensions in both pixels and millimeters
          5. Estimates particle volume using power law formula
          6. Filters particles into two lists based on dimension ranges
    
    @code
    # Process with pre-loaded model and settings
    result = object_process_image(frame, model=my_model, settings=my_settings)
    image_path, boxes, detect_particles, save_particles = result
    
    # Process with database lookup
    result = object_process_image(frame, model_id="yolov8:1.0", settings_id="default")
    @endcode
    
    @see DetectedParticle
    @see CameraSettings
    @see get_model_from_database
    @see get_camera_settings
    """
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
    all_particles = [
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

    # Filter particles based on min_d_detect and max_d_detect (dimension range to report)
    particles_to_detect = [
        p for p in all_particles 
        if settings.min_d_detect <= p.max_d_mm <= settings.max_d_detect
    ]
    
    # Filter particles based on min_d_save and max_d_save (dimension range to save/store)
    particles_to_save = [
        p for p in all_particles 
        if settings.min_d_save <= p.max_d_mm <= settings.max_d_save
    ]

    # Prepare the result with image, bounding boxes, and filtered particle objects
    # Returns: [image, xyxy, particles_to_detect, particles_to_save]
    result = [image, xyxy, particles_to_detect, particles_to_save]

    return result