import sqlite3
from datetime import datetime
from typing import Optional
from dataclasses import dataclass


@dataclass
class ProjectSettings:
    id: int
    vm_number: str
    title: str
    description: str
    iris_main_folder: Optional[str] = None
    iris_classifier_subfolder: Optional[str] = None
    iris_model_subfolder: Optional[str] = None
    csv_interval_seconds: int = 60
    image_processing_interval: float = 1.0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def to_dict(self) -> dict:
        """Convert the settings to a dictionary."""
        return {
            'id': self.id,
            'vm_number': self.vm_number,
            'title': self.title,
            'description': self.description,
            'iris_main_folder': self.iris_main_folder,
            'iris_classifier_subfolder': self.iris_classifier_subfolder,
            'iris_model_subfolder': self.iris_model_subfolder,
            'csv_interval_seconds': self.csv_interval_seconds,
            'image_processing_interval': self.image_processing_interval,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class ProjectSettingsSQLiteProvider:
    def __init__(self, db_path: str = 'project_settings.db'):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS project_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vm_number TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    iris_main_folder TEXT,
                    iris_classifier_subfolder TEXT,
                    iris_model_subfolder TEXT,
                    csv_interval_seconds INTEGER DEFAULT 60,
                    image_processing_interval REAL DEFAULT 1.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Insert default settings if not exists
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM project_settings')
            if cursor.fetchone()[0] == 0:
                cursor.execute('''
                    INSERT INTO project_settings (vm_number, title, description, iris_main_folder, iris_classifier_subfolder, iris_model_subfolder, csv_interval_seconds, image_processing_interval)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', ('VM001', 'Belt Vision Project', 'Default project configuration', '', '', '', 60, 1.0))
            conn.commit()

    def get_current_settings(self) -> Optional[ProjectSettings]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, vm_number, title, description, iris_main_folder, iris_classifier_subfolder, iris_model_subfolder, csv_interval_seconds, image_processing_interval, created_at, updated_at
                FROM project_settings
                ORDER BY id DESC
                LIMIT 1
            ''')
            row = cursor.fetchone()
            if row:
                created_at = datetime.fromisoformat(row[9]) if row[9] else None
                updated_at = datetime.fromisoformat(row[10]) if row[10] else None
                return ProjectSettings(
                    id=row[0],
                    vm_number=row[1],
                    title=row[2],
                    description=row[3],
                    iris_main_folder=row[4],
                    iris_classifier_subfolder=row[5],
                    iris_model_subfolder=row[6],
                    csv_interval_seconds=row[7] if row[7] is not None else 60,
                    image_processing_interval=row[8] if row[8] is not None else 1.0,
                    created_at=created_at,
                    updated_at=updated_at
                )
            return None

    def update_settings(self, vm_number: str, title: str, description: str, 
                        iris_main_folder: str = '', iris_classifier_subfolder: str = '', 
                        iris_model_subfolder: str = '', csv_interval_seconds: int = 60,
                        image_processing_interval: float = 1.0) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM project_settings ORDER BY id DESC LIMIT 1')
            existing = cursor.fetchone()
            
            if existing:
                cursor.execute('''
                    UPDATE project_settings
                    SET vm_number = ?, title = ?, description = ?, iris_main_folder = ?, 
                        iris_classifier_subfolder = ?, iris_model_subfolder = ?, csv_interval_seconds = ?, 
                        image_processing_interval = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (vm_number, title, description, iris_main_folder, iris_classifier_subfolder, 
                      iris_model_subfolder, csv_interval_seconds, image_processing_interval, existing[0]))
            else:
                cursor.execute('''
                    INSERT INTO project_settings (vm_number, title, description, iris_main_folder, 
                                                   iris_classifier_subfolder, iris_model_subfolder, csv_interval_seconds, image_processing_interval)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (vm_number, title, description, iris_main_folder, iris_classifier_subfolder, 
                      iris_model_subfolder, csv_interval_seconds, image_processing_interval))
            
            conn.commit()
            return True

    def get_settings_dict(self) -> Optional[dict]:
        settings = self.get_current_settings()
        if settings:
            return settings.to_dict()
        return None
    
    def get_project_settings(self) -> Optional[ProjectSettings]:
        """Alias for get_current_settings for compatibility."""
        return self.get_current_settings()


# Global instance
project_settings_provider = ProjectSettingsSQLiteProvider()
