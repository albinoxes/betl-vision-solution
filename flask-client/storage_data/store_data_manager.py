import cv2
from pathlib import Path
from datetime import datetime
from typing import Optional


class StoreDataManager:
    def __init__(self):
        # Get the project root (parent of flask-client)
        self.project_root = Path(__file__).parent.parent.parent
        self.raw_data_store = self.project_root / 'raw_data_store'
    
    def get_project_title(self) -> str:
        """Get the current project title from database."""
        from sqlite.project_settings_sqlite_provider import ProjectSettingsSQLiteProvider
        provider = ProjectSettingsSQLiteProvider()
        settings = provider.get_current_settings()
        if settings:
            return settings.title
        return 'default_project'
    
    def ensure_storage_directory(self, project_title: Optional[str] = None) -> Path:
        if project_title is None:
            project_title = self.get_project_title()
        
        storage_path = self.raw_data_store / project_title / 'export'
        storage_path.mkdir(parents=True, exist_ok=True)
        return storage_path
    
    def save_frame(self, image, project_title: Optional[str] = None, filename: Optional[str] = None) -> bool:
        try:
            storage_path = self.ensure_storage_directory(project_title)
            
            if filename is None:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                filename = f"frame_{timestamp}.jpg"
            
            filepath = storage_path / filename
            cv2.imwrite(str(filepath), image)
            return True
        except Exception as e:
            print(f"Error saving frame: {e}")
            return False
    
    def get_storage_path(self, project_title: Optional[str] = None) -> Path:
        if project_title is None:
            project_title = self.get_project_title()
        
        return self.raw_data_store / project_title / 'export'


# Global instance
store_data_manager = StoreDataManager()
