import sqlite3
from datetime import datetime
from typing import Optional, List
from storage_data.store_data_manager import VideoSegment


class VideoStreamSQLiteProvider:
    """
    SQLite provider for storing and retrieving video stream metadata.
    """

    def __init__(self, db_path: str = 'video_stream.db'):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize the database and create tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS video_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    camera_id TEXT NOT NULL,
                    start_time DATETIME NOT NULL,
                    file_path TEXT
                )
            ''')
            conn.commit()

    def insert_segment(self, camera_id: str, start_time: datetime, 
                       file_path: Optional[str] = None) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO video_segments (camera_id, start_time, file_path)
                VALUES (?, ?, ?)
            ''', (
                camera_id,
                start_time.isoformat() if isinstance(start_time, datetime) else start_time,
                file_path
            ))
            conn.commit()
            return cursor.lastrowid

    def get_segment_by_id(self, segment_id: int) -> Optional[VideoSegment]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, camera_id, start_time, file_path
                FROM video_segments
                WHERE id = ?
            ''', (segment_id,))
            row = cursor.fetchone()
            if row:
                return VideoSegment(
                    id=row[0],
                    camera_id=row[1],
                    start_time=datetime.fromisoformat(row[2]) if row[2] else None,
                    file_path=row[3]
                )
            return None

    def get_segments_by_camera(self, camera_id: str) -> List[VideoSegment]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, camera_id, start_time, file_path
                FROM video_segments
                WHERE camera_id = ?
                ORDER BY start_time DESC
            ''', (camera_id,))
            rows = cursor.fetchall()
            return [
                VideoSegment(
                    id=row[0],
                    camera_id=row[1],
                    start_time=datetime.fromisoformat(row[2]) if row[2] else None,
                    file_path=row[3]
                )
                for row in rows
            ]

    def get_all_segments(self) -> List[VideoSegment]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, camera_id, start_time, file_path
                FROM video_segments
                ORDER BY start_time DESC
            ''')
            rows = cursor.fetchall()
            return [
                VideoSegment(
                    id=row[0],
                    camera_id=row[1],
                    start_time=datetime.fromisoformat(row[2]) if row[2] else None,
                    file_path=row[3]
                )
                for row in rows
            ]

    def delete_segment(self, segment_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM video_segments WHERE id = ?', (segment_id,))
            conn.commit()
            return cursor.rowcount > 0

    def delete_segments_by_camera(self, camera_id: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM video_segments WHERE camera_id = ?', (camera_id,))
            conn.commit()
            return cursor.rowcount

    def delete_all_segments(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM video_segments')
            conn.commit()
            return cursor.rowcount

    def update_segment_file_path(self, segment_id: int, file_path: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE video_segments
                SET file_path = ?
                WHERE id = ?
            ''', (file_path, segment_id))
            conn.commit()
            return cursor.rowcount > 0


# Global instance
video_stream_provider = VideoStreamSQLiteProvider()
