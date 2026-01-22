import cv2

# Run boulder detection model
def object_process_image(img2d, model, min_conf, pixels_per_mm, particle_bb_dimension_factor, est_particle_volume_x, est_particle_volume_exp):
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