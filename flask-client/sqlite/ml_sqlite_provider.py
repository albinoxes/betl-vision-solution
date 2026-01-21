import sqlite3
import os
import tempfile
from datetime import datetime
from typing import Optional, Tuple, BinaryIO


class MLSQLiteProvider:
    """
    SQLite provider for storing and retrieving machine learning models and classifiers as BLOBs.
    Supports versioning and temporary file retrieval for runtime use.
    """

    def __init__(self, db_path: str = 'ml_models.db'):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # Drop table if exists to ensure correct schema
            conn.execute('''
                CREATE TABLE IF NOT EXISTS ml_models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    model_type TEXT NOT NULL,
                    description TEXT,
                    data BLOB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(name, version)
                )
            ''')
            # Create index for faster lookups
            conn.execute('CREATE INDEX IF NOT EXISTS idx_ml_models_name_version ON ml_models(name, version)')

    def insert_model(self, name: str, version: str, model_type: str, data: bytes, description: Optional[str] = None) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO ml_models (name, version, model_type, description, data)
                VALUES (?, ?, ?, ?, ?)
            ''', (name, version, model_type, description, data))
            conn.commit()
            return cursor.lastrowid

    def insert_model_from_file(self, name: str, version: str, model_type: str, file_path: str, description: Optional[str] = None) -> int:
        with open(file_path, 'rb') as f:
            data = f.read()
        return self.insert_model(name, version, model_type, data, description)

    def get_model(self, name: str, version: str) -> Optional[Tuple[int, str, str, Optional[str], bytes, datetime, datetime]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, name, version, model_type, description, data, created_at, updated_at
                FROM ml_models
                WHERE name = ? AND version = ?
            ''', (name, version))
            row = cursor.fetchone()
            if row:
                # Convert timestamps back to datetime objects
                created_at = datetime.fromisoformat(row[6]) if row[6] else None
                return (row[0], row[1], row[2], row[3], row[4], row[5], created_at)
            return None

    def get_model_data(self, name: str, version: str) -> Optional[bytes]:
        model = self.get_model(name, version)
        return model[5] if model else None

    def get_model_to_temp_file(self, name: str, version: str, suffix: Optional[str] = None) -> Optional[str]:
        data = self.get_model_data(name, version)
        if data is None:
            return None

        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(data)
            return temp_file.name

    def list_models(self) -> list:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, name, version, model_type, description, created_at
                FROM ml_models
                ORDER BY name, version
            ''')
            return cursor.fetchall()

    def list_model_versions(self, name: str) -> list:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT version, model_type, description, created_at
                FROM ml_models
                WHERE name = ?
                ORDER BY version DESC
            ''', (name,))
            return cursor.fetchall()

    def delete_model(self, name: str, version: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM ml_models WHERE name = ? AND version = ?', (name, version))
            conn.commit()
            return cursor.rowcount > 0

# Convenience instance for global use
ml_provider = MLSQLiteProvider()