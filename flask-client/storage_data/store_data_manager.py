import cv2
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass
from infrastructure.logging.logging_provider import get_logger

# Initialize logger
logger = get_logger()


@dataclass
class VideoSegment:
    """
    Data class representing a video segment record.
    """
    id: int
    camera_id: str
    start_time: datetime
    file_path: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert the video segment to a dictionary."""
        return {
            'id': self.id,
            'camera_id': self.camera_id,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'file_path': self.file_path
        }


class StoreDataManager:
    def __init__(self):
        # Get the project root (parent of flask-client)
        self.project_root = Path(__file__).parent.parent.parent
        self.raw_data_store = self.project_root / 'raw_data_store'
        
        # Track active recording sessions: {session_key: {'folder_start_time': datetime, 'current_folder': str}}
        self.active_sessions = {}
        self.session_duration_minutes = 15
        self.max_sessions = 100  # Limit to prevent unbounded growth
    
    def cleanup_old_sessions(self):
        """Remove sessions that are older than the duration limit."""
        current_time = datetime.now()
        to_remove = []
        
        for session_key, session_info in self.active_sessions.items():
            elapsed_minutes = (current_time - session_info['folder_start_time']).total_seconds() / 60
            if elapsed_minutes > self.session_duration_minutes * 2:  # Keep for 2x duration before cleanup
                to_remove.append(session_key)
        
        for key in to_remove:
            del self.active_sessions[key]
            logger.debug(f"Cleaned up old session: {key}")
    
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
        
        # Create the absolute path and ensure it exists
        absolute_storage_path = self.raw_data_store / project_title / 'export'
        absolute_storage_path.mkdir(parents=True, exist_ok=True)
        
        # Return relative path from project root
        return Path('raw_data_store') / project_title / 'export'
    
    def get_current_session_folder(self, session_key: str, project_title: Optional[str] = None) -> Path:
        """
        Get the current active timestamped folder for a recording session.
        Creates a new folder if none exists or if current folder is older than 15 minutes.
        
        Args:
            session_key: Unique identifier for the recording session (e.g., thread_id)
            project_title: Optional project title
            
        Returns:
            Relative path to the current session folder
        """
        # Periodically cleanup old sessions to prevent memory leak
        if len(self.active_sessions) > self.max_sessions:
            self.cleanup_old_sessions()
        
        if project_title is None:
            project_title = self.get_project_title()
        
        current_time = datetime.now()
        
        # Check if we have an active session and if it's still valid (< 15 minutes old)
        if session_key in self.active_sessions:
            session_info = self.active_sessions[session_key]
            folder_start_time = session_info['folder_start_time']
            elapsed_minutes = (current_time - folder_start_time).total_seconds() / 60
            
            # If less than 15 minutes, return existing folder
            if elapsed_minutes < self.session_duration_minutes:
                return session_info['current_folder']
        
        # Create new timestamped folder
        timestamp = current_time.strftime('%Y%m%d_%H%M%S')
        folder_name = f"session_{timestamp}"
        
        # Create absolute path
        absolute_folder_path = self.raw_data_store / project_title / 'export' / folder_name
        absolute_folder_path.mkdir(parents=True, exist_ok=True)
        
        # Create relative path
        relative_folder_path = Path('raw_data_store') / project_title / 'export' / folder_name
        
        # Update session tracking
        self.active_sessions[session_key] = {
            'folder_start_time': current_time,
            'current_folder': relative_folder_path
        }
        
        return relative_folder_path
    
    def end_session(self, session_key: str):
        """
        End a recording session and clean up tracking.
        
        Args:
            session_key: Unique identifier for the recording session
        """
        if session_key in self.active_sessions:
            del self.active_sessions[session_key]
    
    def save_frame(self, image, session_key: str, project_title: Optional[str] = None, filename: Optional[str] = None) -> bool:
        """
        Save a frame to the storage directory within a timestamped session folder.
        
        Args:
            image: OpenCV image to save
            session_key: Unique identifier for the recording session (e.g., thread_id)
            project_title: Optional project title
            filename: Optional filename
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Get current session folder (creates new one if needed after 15min)
            storage_path = self.get_current_session_folder(session_key, project_title)
            
            if filename is None:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                filename = f"frame_{timestamp}.jpg"
            
            # Convert to absolute path for saving
            absolute_filepath = self.project_root / storage_path / filename
            cv2.imwrite(str(absolute_filepath), image)
            
            # Return relative filepath
            return str(storage_path / filename)
        except Exception as e:
            logger.error(f"Error saving frame: {e}")
            return False
    
    def get_storage_path(self, project_title: Optional[str] = None) -> Path:
        if project_title is None:
            project_title = self.get_project_title()
        
        return self.raw_data_store / project_title / 'export'


# Global instance
store_data_manager = StoreDataManager()
