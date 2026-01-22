# Run belt_status Classifier Model
def classifier_process_image(img2d, classifier_model, class_names, transform):
    # Convert the NumPy array to a PIL Image
    img = Image.fromarray(img2d)

    # If the image is grayscale (1 channel), convert it to RGB
    if img.mode == 'L':
     img = img.convert('RGB')

    # Preprocessing
    img_transformed = transform(img)

    # Inference with belt status classifier model
    output = classifier_model(img_transformed.unsqueeze(0))
    _, predicted_class = torch.max(output, 1)
    belt_status = class_names[predicted_class.item()]
    
    return belt_status