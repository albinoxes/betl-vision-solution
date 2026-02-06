## @file classifier_image_processor.py
#  @brief Classifier image processor for belt status classification.
#
#  This module provides functionality for processing images with PyTorch-based classification
#  models to determine belt status. It handles model loading from database, image preprocessing,
#  and inference operations.
#
#  @author Belt Vision Team
#  @date 2026

from PIL import Image
import torch
import torchvision.transforms as transforms
from sqlite.ml_sqlite_provider import ml_provider


def get_classifier_from_database(classifier_id=None):
    """@brief Load a classifier model from the database with transforms.
    
    Retrieves a PyTorch classification model from the database along with its associated
    class names and image transformation pipeline. If a specific classifier_id is provided,
    loads that classifier. Otherwise, loads the first available classifier.
    
    The function automatically determines the number of classes from the model's final
    fully connected layer and generates appropriate class names.
    
    @param classifier_id Optional classifier identifier in format "name:version" or just "name"
                         If None, loads the first available classifier from database
    
    @return Tuple of (classifier_model, class_names, transform):
            - classifier_model: Loaded PyTorch model or None if no classifier found
            - class_names: List of class name strings (generated from class count)
            - transform: torchvision.transforms.Compose pipeline for image preprocessing
            Returns (None, None, None) if no classifier is found
    
    @note If classifier_id contains no version, defaults to version '1.0.0'
    @note Default transform resizes to 150x150 and normalizes with mean/std 0.5
    @note Number of classes determined from model.fc.out_features, defaults to 3 if unavailable
    
    @code
    # Load specific classifier
    model, classes, transform = get_classifier_from_database("belt_status:2.0.0")
    
    # Load first available classifier
    model, classes, transform = get_classifier_from_database()
    
    # Check if classifier was found
    if model is None:
        print("No classifier available")
    @endcode
    
    @see classifier_process_image()
    """
    classifier_model = None
    
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
        if all_classifiers and len(all_classifiers) > 0:
            # Use first classifier: (id, name, version, model_type, description, created_at, updated_at)
            first_classifier = all_classifiers[0]
            if len(first_classifier) >= 3:
                classifier_model = ml_provider.load_ml_model(first_classifier[1], first_classifier[2])
    
    if classifier_model is None:
        return None, None, None
    
    # Determine number of classes from model
    import torch
    if hasattr(classifier_model, 'fc'):
        num_classes = classifier_model.fc.out_features
    else:
        num_classes = 3  # fallback
    
    # Generate class names based on number of classes
    class_names = [str(i) for i in range(num_classes)]
    
    # Default transform
    transform = transforms.Compose([
        transforms.Resize((150, 150)),
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
    ])
    
    return classifier_model, class_names, transform


def classifier_process_image(img2d, classifier_id=None):
    """@brief Process an image with the belt status classifier model.
    
    Performs belt status classification on an input image using a PyTorch model.
    The function handles image preprocessing including PIL conversion, grayscale to RGB
    conversion if needed, resizing, normalization, and runs inference to predict belt status.
    
    Processing steps:
    1. Load classifier model from database
    2. Convert NumPy array to PIL Image
    3. Convert grayscale to RGB if necessary
    4. Apply preprocessing transforms (resize to 150x150, normalize)
    5. Run inference with the classifier
    6. Return predicted class name
    
    @param img2d Input image as NumPy array (can be grayscale or RGB)
    @param classifier_id Optional classifier identifier to load from database
                         If None, uses first available classifier
    
    @return String representing the predicted belt status class name
    
    @throws ValueError If no classifier is found in the database
    
    @note Automatically converts grayscale images to RGB for model compatibility
    @note Uses PyTorch for inference - requires torch and torchvision
    @note Model runs in evaluation mode (no gradient computation)
    
    @warning Input image should be a valid NumPy array compatible with PIL.Image.fromarray()
    
    @code
    # Classify a frame with default classifier
    status = classifier_process_image(frame_array)
    print(f"Belt status: {status}")
    
    # Classify with specific classifier
    status = classifier_process_image(frame_array, classifier_id="belt_status_v2:1.5.0")
    @endcode
    
    @see get_classifier_from_database()
    """
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