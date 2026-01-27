import csv
from pathlib import Path
from datetime import datetime
from typing import Any, Optional


class IrisInputProcessor:
    """
    Processor for generating IRIS input CSV files.
    """
    
    # CSV interval in seconds - data accumulates in same file for this duration
    CSV_INTERVAL_SECONDS = 60  # 1 minute by default
    
    def __init__(self):
        # Track active CSV files: {folder_type: {'path': str, 'start_time': datetime}}
        self.active_csv_files = {}
    
    def create_iris_csv_input(self, 
                             csv_name: str, 
                             project_title: str, 
                             file_creation_timestamp: datetime,
                             status_timestamp: datetime,
                             data: Any,
                             iris_main_folder: str,
                             subfolder: str,
                             folder_type: str = 'classifier',
                             image_filename: str = '') -> Optional[str]:
        """
        Create CSV file with IRIS input data.
        
        Args:
            csv_name: Name of the CSV file (without .csv extension)
            project_title: Title of the project
            file_creation_timestamp: Timestamp when file was created
            status_timestamp: Timestamp of the status/result
            data: The result or status data to store
            iris_main_folder: Main folder path for IRIS data
            subfolder: Subfolder within the main IRIS folder (e.g., model or classifier subfolder)
            folder_type: Type of folder - 'model' or 'classifier'
            image_filename: Name of the stored image file (for model results)
            
        Returns:
            Path to the created CSV file, or None if failed
        """
        try:
            # Get solution root (3 levels up from this file: flask-client/iris_communication/iris_input_processor.py)
            solution_root = Path(__file__).parent.parent.parent
            
            # Create full path: root / iris_main_folder / subfolder
            iris_path = solution_root / iris_main_folder / subfolder
            iris_path.mkdir(parents=True, exist_ok=True)
            
            # Check if we need to create a new CSV file or append to existing
            create_new_file = False
            csv_filepath = None
            
            if folder_type in self.active_csv_files:
                # Check if interval has elapsed
                active_info = self.active_csv_files[folder_type]
                elapsed_seconds = (datetime.now() - active_info['start_time']).total_seconds()
                
                if elapsed_seconds >= self.CSV_INTERVAL_SECONDS:
                    # Interval elapsed, create new file
                    create_new_file = True
                    print(f"[IRIS] {folder_type.capitalize()} CSV interval elapsed ({elapsed_seconds:.1f}s), creating new file")
                else:
                    # Use existing file
                    csv_filepath = Path(active_info['path'])
                    print(f"[IRIS] Appending to existing {folder_type} CSV: {csv_filepath.name}")
            else:
                # No active file, create new one
                create_new_file = True
            
            # Create new CSV file if needed
            if create_new_file:
                csv_filename = f"{csv_name}.csv"
                csv_filepath = iris_path / csv_filename
                print(f"[IRIS] Creating new CSV file: {csv_filepath}")
                
                # Track this as the active CSV file
                self.active_csv_files[folder_type] = {
                    'path': str(csv_filepath),
                    'start_time': datetime.now()
                }
            
            # Format timestamps
            file_creation_str = file_creation_timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')
            status_str = status_timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')
            
            # Write CSV file (create with header or append)
            mode = 'w' if create_new_file else 'a'
            with open(csv_filepath, mode, newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                
                if folder_type == 'model':
                    # Model results: extract detection data from result format [image, xyxy, particles]
                    # Write header only when creating new file
                    if create_new_file:
                        writer.writerow(['timestamp', 'image', 'xyxy', 'conf', 'width_px', 'width_mm', 
                                       'height_mm', 'max_d_mm', 'volume_est'])
                    
                    # Extract particles from result
                    if isinstance(data, list) and len(data) >= 3:
                        image_data = data[0]
                        xyxy_data = data[1]
                        particles = data[2]
                        
                        # Write one row per detection
                        for i, particle in enumerate(particles):
                            # Get corresponding bounding box
                            bbox = xyxy_data[i] if i < len(xyxy_data) else []
                            bbox_str = f"[{','.join(map(str, bbox))}]" if bbox else ''
                            
                            writer.writerow([
                                status_str,
                                image_filename if image_filename else 'frame',  # Image filename
                                bbox_str,
                                getattr(particle, 'conf', ''),
                                getattr(particle, 'width_px', ''),
                                getattr(particle, 'width_mm', ''),
                                getattr(particle, 'height_mm', ''),
                                getattr(particle, 'max_d_mm', ''),
                                getattr(particle, 'volume_est', '')
                            ])
                else:
                    # Classifier results: simple format
                    if create_new_file:
                        writer.writerow(['ProjectTitle', 'FileCreationTimestamp', 'StatusTimestamp', 'Data'])
                    writer.writerow([project_title, file_creation_str, status_str, str(data)])
            
            return str(csv_filepath)
            
        except Exception as e:
            print(f"Error generating IRIS input data: {e}")
            return None
    
    def generate_iris_input_data(self, project_settings, timestamp: datetime, data: Any, folder_type: str, image_filename: str = '') -> Optional[str]:
        """
        Wrapper method to generate IRIS input CSV data with automatic configuration.
        
        Args:
            project_settings: ProjectSettings object containing IRIS configuration
            timestamp: Timestamp for the data
            data: The result or status data to store
            folder_type: Type of folder - 'model' or 'classifier'
            image_filename: Name of the stored image file (for model results)
            
        Returns:
            Path to the created CSV file, or None if not created
        """
        if not project_settings:
            print(f"[IRIS] Skipping {folder_type} CSV - No project settings found")
            return None
        
        if not project_settings.iris_main_folder:
            print(f"[IRIS] Skipping {folder_type} CSV - No main folder configured")
            return None
        
        # Determine subfolder based on type
        if folder_type == 'model':
            subfolder = project_settings.iris_model_subfolder
            if not subfolder:
                print(f"[IRIS] Skipping model CSV - No model subfolder configured")
                return None
        elif folder_type == 'classifier':
            subfolder = project_settings.iris_classifier_subfolder
            if not subfolder:
                print(f"[IRIS] Skipping classifier CSV - No classifier subfolder configured")
                return None
        else:
            print(f"[IRIS] Invalid folder type: {folder_type}")
            return None
        
        # Generate CSV name
        csv_name = f"{subfolder}_{timestamp.strftime('%Y%m%d_%H%M%S_%f')}"
        print(f"[IRIS] Generating {folder_type} CSV: {csv_name}")
        
        # Create CSV
        csv_path = self.create_iris_csv_input(
            csv_name=csv_name,
            project_title=project_settings.title,
            file_creation_timestamp=timestamp,
            status_timestamp=timestamp,
            data=data,
            iris_main_folder=project_settings.iris_main_folder,
            subfolder=subfolder,
            folder_type=folder_type,
            image_filename=image_filename
        )
        
        if csv_path:
            print(f"[IRIS] {folder_type.capitalize()} CSV created at: {csv_path}")
        
        return csv_path


# Global instance
iris_input_processor = IrisInputProcessor()
