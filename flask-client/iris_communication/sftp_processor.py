import os
import paramiko
from sqlite.sftp_sqlite_provider import SftpServerInfos
from infrastructure.logging.logging_provider import get_logger

# Initialize logger
logger = get_logger()


class SftpProcessor:
    """Handles SFTP file transfer operations."""
    
    def __init__(self):
        pass
    
    def transferData(self, sftp_server_info: SftpServerInfos, file_path: str, project_settings, folder_type: str) -> dict:
        """
        Transfer a single CSV file to an SFTP server.
        
        Args:
            sftp_server_info: SftpServerInfos object containing server credentials
            file_path: Local file path to the CSV file to transfer
            project_settings: ProjectSettings object containing IRIS folder configuration
            folder_type: Type of data - 'model' or 'classifier'
            
        Returns:
            dict: Summary of transfer results with success/failure information
        """
        if not os.path.exists(file_path):
            return {
                'success': False,
                'error': f'File not found: {file_path}'
            }
        
        if not os.path.isfile(file_path):
            return {
                'success': False,
                'error': f'Path is not a file: {file_path}'
            }
        
        # Validate project settings
        if not project_settings:
            return {
                'success': False,
                'error': 'Project settings not found. Please configure project settings first.'
            }
        
        transport = None
        sftp = None
        
        try:
            # Connect to SFTP server
            transport = paramiko.Transport((sftp_server_info.server_name, 22))
            transport.connect(username=sftp_server_info.username, password=sftp_server_info.password)
            sftp = paramiko.SFTPClient.from_transport(transport)
            
            # Get file name from path
            file_name = os.path.basename(file_path)
            
            # Determine the target directory based on the folder type and project settings
            if folder_type == 'model':
                # Model data - use iris_main_folder/iris_model_subfolder
                target_directory = f'{project_settings.iris_main_folder}/{project_settings.iris_model_subfolder}'
            elif folder_type == 'classifier':
                # Classifier data - use iris_main_folder/iris_classifier_subfolder
                target_directory = f'{project_settings.iris_main_folder}/{project_settings.iris_classifier_subfolder}'
            else:
                # Default to iris_main_folder if folder type doesn't match
                target_directory = project_settings.iris_main_folder
            
            # Ensure target directory exists (create if it doesn't)
            try:
                sftp.stat(target_directory)
            except FileNotFoundError:
                # Create directory if it doesn't exist
                self._create_remote_directory(sftp, target_directory)
            
            # Upload the file to the target directory
            remote_file_path = f"{target_directory}/{file_name}"
            sftp.put(file_path, remote_file_path)
            
            logger.info(f"Successfully uploaded {file_name} to {remote_file_path}")
            
            return {
                'success': True,
                'message': f'Successfully uploaded {file_name}',
                'file': file_name,
                'local_path': file_path,
                'remote_path': remote_file_path
            }
            
        except Exception as e:
            logger.error(f"Error during SFTP upload: {e}")
            return {
                'success': False,
                'error': f'SFTP upload error: {str(e)}'
            }
        finally:
            # Always close connections to prevent socket leaks
            if sftp:
                try:
                    sftp.close()
                except:
                    pass
            if transport:
                try:
                    transport.close()
                except:
                    pass
    
    def _create_remote_directory(self, sftp, remote_path: str):
        """
        Create a remote directory and all parent directories if they don't exist.
        
        Args:
            sftp: Active SFTP client connection
            remote_path: Remote directory path to create
        """
        dirs = []
        path = remote_path
        
        # Build list of directories to create
        while path and path != '/':
            dirs.append(path)
            path = os.path.dirname(path)
        
        # Create directories from root to leaf
        for directory in reversed(dirs):
            try:
                sftp.stat(directory)
            except FileNotFoundError:
                try:
                    sftp.mkdir(directory)
                    logger.info(f"Created remote directory: {directory}")
                except Exception as e:
                    logger.warning(f"Warning: Could not create directory {directory}: {e}")


# Global instance
sftp_processor = SftpProcessor()
