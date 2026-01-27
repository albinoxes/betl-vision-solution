import sqlite3
from typing import Optional, List
from dataclasses import dataclass


@dataclass
class SftpServerInfos:
    id: int
    server_name: str
    username: str
    password: str
    
    def to_dict(self) -> dict:
        """Convert the SFTP server info to a dictionary."""
        return {
            'id': self.id,
            'server_name': self.server_name,
            'username': self.username,
            'password': self.password
        }


class SftpSQLiteProvider:
    def __init__(self, db_path: str = 'sftp_servers.db'):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize the database and create tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sftp_servers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_name TEXT NOT NULL,
                    username TEXT NOT NULL,
                    password TEXT NOT NULL
                )
            ''')
            conn.commit()

    def insert_server(self, server_name: str, username: str, password: str) -> Optional[int]:
        """Insert a new SFTP server configuration."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO sftp_servers (server_name, username, password)
                    VALUES (?, ?, ?)
                ''', (server_name, username, password))
                conn.commit()
                return cursor.lastrowid
        except sqlite3.IntegrityError:
            return None

    def get_server_by_id(self, server_id: int) -> Optional[SftpServerInfos]:
        """Get SFTP server configuration by ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, server_name, username, password
                FROM sftp_servers
                WHERE id = ?
            ''', (server_id,))
            row = cursor.fetchone()
            if row:
                return SftpServerInfos(id=row[0], server_name=row[1], username=row[2], password=row[3])
            return None

    def get_all_servers(self) -> List[SftpServerInfos]:
        """Get all SFTP server configurations."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, server_name, username, password
                FROM sftp_servers
                ORDER BY id ASC
            ''')
            rows = cursor.fetchall()
            return [SftpServerInfos(id=row[0], server_name=row[1], username=row[2], password=row[3]) for row in rows]

    def update_server(self, server_id: int, server_name: str, username: str, password: str) -> bool:
        """Update an existing SFTP server configuration."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE sftp_servers
                    SET server_name = ?, username = ?, password = ?
                    WHERE id = ?
                ''', (server_name, username, password, server_id))
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.IntegrityError:
            return False

    def delete_server(self, server_id: int) -> bool:
        """Delete an SFTP server configuration."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM sftp_servers WHERE id = ?', (server_id,))
            conn.commit()
            return cursor.rowcount > 0

    def delete_all_servers(self) -> int:
        """Delete all SFTP server configurations."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM sftp_servers')
            conn.commit()
            return cursor.rowcount


# Global instance
sftp_provider = SftpSQLiteProvider()
