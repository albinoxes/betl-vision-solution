import sqlite3
from datetime import datetime
from typing import Optional, Tuple


class ProjectSettingsSQLiteProvider:
    """
    SQLite provider for storing and retrieving project settings.
    """

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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Insert default settings if not exists
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM project_settings')
            if cursor.fetchone()[0] == 0:
                cursor.execute('''
                    INSERT INTO project_settings (vm_number, title, description)
                    VALUES (?, ?, ?)
                ''', ('VM001', 'Belt Vision Project', 'Default project configuration'))
            conn.commit()

    def get_current_settings(self) -> Optional[Tuple[int, str, str, str, datetime, datetime]]:
        """
        Get the current project settings (assumes single row configuration).
        Returns: (id, vm_number, title, description, created_at, updated_at)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, vm_number, title, description, created_at, updated_at
                FROM project_settings
                ORDER BY id DESC
                LIMIT 1
            ''')
            row = cursor.fetchone()
            if row:
                created_at = datetime.fromisoformat(row[4]) if row[4] else None
                updated_at = datetime.fromisoformat(row[5]) if row[5] else None
                return (row[0], row[1], row[2], row[3], created_at, updated_at)
            return None

    def update_settings(self, vm_number: str, title: str, description: str) -> bool:
        """
        Update the project settings. Creates a new entry if none exists.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM project_settings ORDER BY id DESC LIMIT 1')
            existing = cursor.fetchone()
            
            if existing:
                cursor.execute('''
                    UPDATE project_settings
                    SET vm_number = ?, title = ?, description = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (vm_number, title, description, existing[0]))
            else:
                cursor.execute('''
                    INSERT INTO project_settings (vm_number, title, description)
                    VALUES (?, ?, ?)
                ''', (vm_number, title, description))
            
            conn.commit()
            return True

    def get_settings_dict(self) -> Optional[dict]:
        """
        Get the current settings as a dictionary.
        """
        settings = self.get_current_settings()
        if settings:
            return {
                'id': settings[0],
                'vm_number': settings[1],
                'title': settings[2],
                'description': settings[3],
                'created_at': settings[4].isoformat() if settings[4] else None,
                'updated_at': settings[5].isoformat() if settings[5] else None
            }
        return None
