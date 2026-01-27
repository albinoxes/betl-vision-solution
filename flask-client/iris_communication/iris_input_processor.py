import csv
from pathlib import Path
from datetime import datetime
from typing import Any, Optional


class IrisInputProcessor:
    """
    Processor for generating IRIS input CSV files.
    """
    
    def __init__(self):
        pass
    
    def create_iris_csv_input(self, 
                             csv_name: str, 
                             project_title: str, 
                             file_creation_timestamp: datetime,
                             status_timestamp: datetime,
                             data: Any,
                             iris_main_folder: str,
                             subfolder: str) -> Optional[str]:
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
            
        Returns:
            Path to the created CSV file, or None if failed
        """
        try:
            # Get solution root (3 levels up from this file: flask-client/iris_communication/iris_input_processor.py)
            solution_root = Path(__file__).parent.parent.parent
            print(f"[IRIS] Solution root: {solution_root}")
            
            # Create full path: root / iris_main_folder / subfolder
            iris_path = solution_root / iris_main_folder / subfolder
            print(f"[IRIS] Creating directory: {iris_path}")
            iris_path.mkdir(parents=True, exist_ok=True)
            
            # Create CSV file path
            csv_filename = f"{csv_name}.csv"
            csv_filepath = iris_path / csv_filename
            print(f"[IRIS] Writing CSV file: {csv_filepath}")
            
            # Format timestamps
            file_creation_str = file_creation_timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')
            status_str = status_timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')
            
            # Write CSV file
            with open(csv_filepath, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                
                # Write header
                writer.writerow(['ProjectTitle', 'FileCreationTimestamp', 'StatusTimestamp', 'Data'])
                
                # Write data row
                writer.writerow([project_title, file_creation_str, status_str, str(data)])
            
            return str(csv_filepath)
            
        except Exception as e:
            print(f"Error generating IRIS input data: {e}")
            return None
    
    def generate_iris_input_data(self, project_settings, timestamp: datetime, data: Any, folder_type: str) -> Optional[str]:
        """
        Wrapper method to generate IRIS input CSV data with automatic configuration.
        
        Args:
            project_settings: ProjectSettings object containing IRIS configuration
            timestamp: Timestamp for the data
            data: The result or status data to store
            folder_type: Type of folder - 'model' or 'classifier'
            
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
            subfolder=subfolder
        )
        
        if csv_path:
            print(f"[IRIS] {folder_type.capitalize()} CSV created at: {csv_path}")
        
        return csv_path


# Global instance
iris_input_processor = IrisInputProcessor()
