import sqlite3
from datetime import datetime
from typing import Optional, Tuple, List


class CameraSettingsSQLiteProvider:
    """
    SQLite provider for storing and retrieving camera settings for boulder detection.
    """

    def __init__(self, db_path: str = 'camera_settings.db'):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # Create table with new columns
            conn.execute('''
                CREATE TABLE IF NOT EXISTS camera_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    min_conf REAL NOT NULL DEFAULT 0.8,
                    min_d_detect INTEGER NOT NULL DEFAULT 200,
                    min_d_save INTEGER NOT NULL DEFAULT 200,
                    max_d_detect INTEGER NOT NULL DEFAULT 10000,
                    max_d_save INTEGER NOT NULL DEFAULT 10000,
                    particle_bb_dimension_factor REAL NOT NULL DEFAULT 0.9,
                    est_particle_volume_x REAL NOT NULL DEFAULT 8.357470139e-11,
                    est_particle_volume_exp REAL NOT NULL DEFAULT 3.02511466443,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Add new columns to existing table if they don't exist (migration)
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(camera_settings)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'max_d_detect' not in columns:
                conn.execute('ALTER TABLE camera_settings ADD COLUMN max_d_detect INTEGER NOT NULL DEFAULT 10000')
                print("[Migration] Added max_d_detect column")
            
            if 'max_d_save' not in columns:
                conn.execute('ALTER TABLE camera_settings ADD COLUMN max_d_save INTEGER NOT NULL DEFAULT 10000')
                print("[Migration] Added max_d_save column")
            
            # Insert default settings if not exists
            cursor.execute('SELECT COUNT(*) FROM camera_settings WHERE name = ?', ('default',))
            if cursor.fetchone()[0] == 0:
                cursor.execute('''
                    INSERT INTO camera_settings (name, min_conf, min_d_detect, min_d_save, max_d_detect, max_d_save, particle_bb_dimension_factor, est_particle_volume_x, est_particle_volume_exp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', ('default', 0.8, 200, 200, 10000, 10000, 0.9, 8.357470139e-11, 3.02511466443))
            conn.commit()

    def insert_settings(self, name: str, min_conf: float, min_d_detect: int, min_d_save: int,
                       max_d_detect: int, max_d_save: int,
                       particle_bb_dimension_factor: float, est_particle_volume_x: float, est_particle_volume_exp: float) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO camera_settings (name, min_conf, min_d_detect, min_d_save, max_d_detect, max_d_save, particle_bb_dimension_factor, est_particle_volume_x, est_particle_volume_exp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (name, min_conf, min_d_detect, min_d_save, max_d_detect, max_d_save, particle_bb_dimension_factor, est_particle_volume_x, est_particle_volume_exp))
            conn.commit()
            return cursor.lastrowid

    def get_settings(self, name: str) -> Optional[Tuple[int, str, float, int, int, int, int, float, float, float, datetime, datetime]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, name, min_conf, min_d_detect, min_d_save, max_d_detect, max_d_save, particle_bb_dimension_factor, est_particle_volume_x, est_particle_volume_exp, created_at, updated_at
                FROM camera_settings
                WHERE name = ?
            ''', (name,))
            row = cursor.fetchone()
            if row:
                created_at = datetime.fromisoformat(row[10]) if row[10] else None
                updated_at = datetime.fromisoformat(row[11]) if row[11] else None
                return (row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9], created_at, updated_at)
            return None

    def list_settings(self) -> List[Tuple[int, str, float, int, int, int, int, float, float, float, str, str]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, name, min_conf, min_d_detect, min_d_save, max_d_detect, max_d_save, particle_bb_dimension_factor, est_particle_volume_x, est_particle_volume_exp, created_at, updated_at
                FROM camera_settings
                ORDER BY name
            ''')
            return cursor.fetchall()

    def update_settings(self, name: str, min_conf: float = None, min_d_detect: int = None, min_d_save: int = None,
                       max_d_detect: int = None, max_d_save: int = None,
                       particle_bb_dimension_factor: float = None, est_particle_volume_x: float = None, est_particle_volume_exp: float = None) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            updates = []
            params = []
            if min_conf is not None:
                updates.append('min_conf = ?')
                params.append(min_conf)
            if min_d_detect is not None:
                updates.append('min_d_detect = ?')
                params.append(min_d_detect)
            if min_d_save is not None:
                updates.append('min_d_save = ?')
                params.append(min_d_save)
            if max_d_detect is not None:
                updates.append('max_d_detect = ?')
                params.append(max_d_detect)
            if max_d_save is not None:
                updates.append('max_d_save = ?')
                params.append(max_d_save)
            if particle_bb_dimension_factor is not None:
                updates.append('particle_bb_dimension_factor = ?')
                params.append(particle_bb_dimension_factor)
            if est_particle_volume_x is not None:
                updates.append('est_particle_volume_x = ?')
                params.append(est_particle_volume_x)
            if est_particle_volume_exp is not None:
                updates.append('est_particle_volume_exp = ?')
                params.append(est_particle_volume_exp)
            if not updates:
                return False
            updates.append('updated_at = CURRENT_TIMESTAMP')
            query = f'UPDATE camera_settings SET {", ".join(updates)} WHERE name = ?'
            params.append(name)
            cursor.execute(query, params)
            conn.commit()
            return cursor.rowcount > 0

    def delete_settings(self, name: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM camera_settings WHERE name = ?', (name,))
            conn.commit()
            return cursor.rowcount > 0

    def get_default_settings(self) -> Optional[Tuple[int, str, float, int, int, int, int, float, float, float, datetime, datetime]]:
        return self.get_settings('default')


# Convenience instance for global use
camera_settings_provider = CameraSettingsSQLiteProvider()