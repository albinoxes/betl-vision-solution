import csv
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Any, Optional


class IrisInputProcessor:
    """
    Processor for generating IRIS input CSV files.
    """
    
    def __init__(self):
        # Track active CSV files: {folder_type: {'path': str, 'start_time': datetime, 'interval': int}}
        self.active_csv_files = {}
        # Track last processing time for calculating time_diff and images_per_second
        self.last_processing_time = {}
    
    def _calculate_timing_metrics(self, folder_type: str) -> tuple[float, float]:
        current_time = datetime.now()
        time_diff = 0.0
        images_per_second = 0.0
        
        if folder_type in self.last_processing_time:
            time_diff = (current_time - self.last_processing_time[folder_type]).total_seconds()
            if time_diff > 0:
                images_per_second = 1.0 / time_diff
        
        self.last_processing_time[folder_type] = current_time
        return time_diff, images_per_second
    
    def _transform_model_data_to_dataframe(self, data: Any, status_str: str, image_filename: str, 
                                          time_diff: float, images_per_second: float) -> Optional[pd.DataFrame]:
        if not isinstance(data, list) or len(data) < 3:
            return None
        
        image_data = data[0]
        xyxy_data = data[1]
        particles = data[2]
        
        # Prepare data rows
        rows = []
        for i, particle in enumerate(particles):
            # Get corresponding bounding box
            bbox = xyxy_data[i] if i < len(xyxy_data) else []
            
            rows.append({
                'timestamp': status_str,
                'image': image_filename if image_filename else 'frame',
                'xyxy': bbox,
                'conf': getattr(particle, 'conf', 0.0),
                'width_px': getattr(particle, 'width_px', 0),
                'height_px': getattr(particle, 'height_px', 0),
                'width_mm': getattr(particle, 'width_mm', 0.0),
                'height_mm': getattr(particle, 'height_mm', 0.0),
                'max_d_mm': getattr(particle, 'max_d_mm', 0.0),
                'volume_est': getattr(particle, 'volume_est', 0.0),
                'time_diff': time_diff,
                'images_per_second': images_per_second
            })
        
        # Create DataFrame
        df = pd.DataFrame(rows)
        
        # Format xyxy as comma-separated string
        df['xyxy'] = df['xyxy'].apply(lambda x: ', '.join(map(str, x)) if isinstance(x, (list, tuple)) else str(x))
        
        # Format confidence with 2 decimal places
        df['conf'] = df['conf'].apply(lambda x: '{:.2f}'.format(x) if isinstance(x, (int, float)) else str(x))
        
        # Format images_per_second with 2 decimal places
        df['images_per_second'] = df['images_per_second'].apply(lambda x: '{:.2f}'.format(x))
        
        return df
    
    def create_iris_csv_input(self, 
                             csv_name: str, 
                             project_title: str, 
                             file_creation_timestamp: datetime,
                             status_timestamp: datetime,
                             data: Any,
                             iris_main_folder: str,
                             subfolder: str,
                             folder_type: str = 'classifier',
                             image_filename: str = '',
                             csv_interval_seconds: int = 60) -> Optional[str]:
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
            csv_interval_seconds: Seconds to accumulate data in same CSV file
            
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
                
                if elapsed_seconds >= csv_interval_seconds:
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
                    'start_time': datetime.now(),
                    'interval': csv_interval_seconds
                }
            
            # Format timestamps
            file_creation_str = file_creation_timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')
            status_str = status_timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')
            
            # Write CSV file (create with header or append)
            mode = 'w' if create_new_file else 'a'
            
            if folder_type == 'model':
                # Model results: transform and write using pandas
                time_diff, images_per_second = self._calculate_timing_metrics(folder_type)
                df = self._transform_model_data_to_dataframe(data, status_str, image_filename, 
                                                            time_diff, images_per_second)
                
                if df is not None:
                    # Write to CSV (with or without header based on mode)
                    df.to_csv(csv_filepath, mode=mode, index=False, header=create_new_file)
            else:
                # Classifier results: simple format using csv writer
                with open(csv_filepath, mode, newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile)
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
        
        # Get CSV interval from project settings
        csv_interval = getattr(project_settings, 'csv_interval_seconds', 60)
        
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
            image_filename=image_filename,
            csv_interval_seconds=csv_interval
        )
        
        if csv_path:
            print(f"[IRIS] {folder_type.capitalize()} CSV created at: {csv_path}")
        
        return csv_path


# Global instance
iris_input_processor = IrisInputProcessor()
