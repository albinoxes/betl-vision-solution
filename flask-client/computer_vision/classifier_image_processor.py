from PIL import Image
import torch
import torchvision.transforms as transforms
from sqlite.ml_sqlite_provider import ml_provider


def get_classifier_from_database(classifier_id=None):
    if classifier_id is not None:
        # Parse classifier_id as "name:version"
        if ':' in classifier_id:
            name, version = classifier_id.split(':', 1)
        else:
            name = classifier_id
            version = '1.0.0'
        classifier_model = ml_provider.load_ml_model(name, version)
    else:
        # Get first available classifier
        all_classifiers = ml_provider.list_classifiers()
        if not all_classifiers:
            return None, None, None
        # Use first classifier: (id, name, version, model_type, description, created_at, updated_at)
        first_classifier = all_classifiers[0]
        classifier_model = ml_provider.load_ml_model(first_classifier[1], first_classifier[2])
    
    # Default class names and transform
    class_names = ['0', '2', '1']
    transform = transforms.Compose([
        transforms.Resize((150, 150)),
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
    ])
    
    return classifier_model, class_names, transform


# Run belt_status Classifier Model
def classifier_process_image(img2d, classifier_id=None):
    # Get classifier from database
    classifier_model, class_names, transform = get_classifier_from_database(classifier_id)
    if classifier_model is None:
        raise ValueError("No classifier found in database")
    
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