import sqlite3
from typing import Optional, List
from dataclasses import dataclass


@dataclass
class ModelStatus:
    id: int
    name: str
    
    def to_dict(self) -> dict:
        """Convert the model status to a dictionary."""
        return {
            'id': self.id,
            'name': self.name
        }


class ModelStatusSQLiteProvider:
    def __init__(self, db_path: str = 'model_status.db'):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize the database and create tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS model_status (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE
                )
            ''')
            conn.commit()

    def insert_status(self, id: int, name: str) -> bool:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO model_status (id, name)
                    VALUES (?, ?)
                ''', (id, name))
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            return False

    def get_status_by_id(self, status_id: int) -> Optional[ModelStatus]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, name
                FROM model_status
                WHERE id = ?
            ''', (status_id,))
            row = cursor.fetchone()
            if row:
                return ModelStatus(id=row[0], name=row[1])
            return None

    def get_all_statuses(self) -> List[ModelStatus]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, name
                FROM model_status
                ORDER BY id ASC
            ''')
            rows = cursor.fetchall()
            return [ModelStatus(id=row[0], name=row[1]) for row in rows]

    def update_status(self, old_id: int, new_id: int, name: str) -> bool:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # If ID is changing, we need to delete and insert
                if old_id != new_id:
                    cursor.execute('DELETE FROM model_status WHERE id = ?', (old_id,))
                    cursor.execute('INSERT INTO model_status (id, name) VALUES (?, ?)', (new_id, name))
                else:
                    cursor.execute('''
                        UPDATE model_status
                        SET name = ?
                        WHERE id = ?
                    ''', (name, new_id))
                conn.commit()
                return cursor.rowcount > 0 or old_id != new_id
        except sqlite3.IntegrityError:
            return False

    def delete_status(self, status_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM model_status WHERE id = ?', (status_id,))
            conn.commit()
            return cursor.rowcount > 0

    def delete_all_statuses(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM model_status')
            conn.commit()
            return cursor.rowcount


# Global instance
model_status_provider = ModelStatusSQLiteProvider()
