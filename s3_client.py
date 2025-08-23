import boto3
from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError
from botocore.config import Config
import os
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime
import mimetypes
from loguru import logger
from config import S3Config
import hashlib
from tqdm import tqdm

class S3Client:
    """AWS S3 client for uploading Supreme Court judgment files"""
    
    def __init__(self, config: S3Config):
        self.config = config
        self.s3_client = None
        self._initialize_client()
    
    def _initialize_client(self):

        """Initialize S3 client with configuration"""

        try:
            # Configure boto3 with retry settings
            boto_config = Config(
                region_name=self.config.aws_region,
                retries={
                    'max_attempts': 3,
                    'mode': 'adaptive'
                },
                max_pool_connections=50
            )
    

            # Create S3 client
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=self.config.aws_access_key_id,
                aws_secret_access_key=self.config.aws_secret_access_key,
                config=boto_config
            )
            
            # Test connection by listing buckets
            self.s3_client.list_buckets()
            
            logger.info(f"S3 client initialized successfully for region: {self.config.aws_region}")
            
        except NoCredentialsError:
            logger.error("AWS credentials not found")
            raise
        except PartialCredentialsError:
            logger.error("Incomplete AWS credentials")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize S3 client: {e}")
            raise
    
    def _ensure_bucket_exists(self) -> bool:
        """Ensure the S3 bucket exists, create if it doesn't"""
        try:
            # Check if bucket exists
            self.s3_client.head_bucket(Bucket=self.config.bucket_name)
            logger.info(f"Bucket {self.config.bucket_name} exists")
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            
            if error_code == '404':
                # Bucket doesn't exist, try to create it
                try:
                    if self.config.aws_region == 'us-east-1':
                        # us-east-1 doesn't need LocationConstraint
                        self.s3_client.create_bucket(Bucket=self.config.bucket_name)
                    else:
                        self.s3_client.create_bucket(
                            Bucket=self.config.bucket_name,
                            CreateBucketConfiguration={'LocationConstraint': self.config.aws_region}
                        )
                    
                    logger.info(f"Created bucket: {self.config.bucket_name}")
                    return True
                    
                except ClientError as create_error:
                    logger.error(f"Failed to create bucket {self.config.bucket_name}: {create_error}")
                    return False
            else:
                logger.error(f"Error checking bucket {self.config.bucket_name}: {e}")
                return False
    
    def _generate_s3_key(self, file_name: str, judgment_date: str = None, case_number: str = None) -> str:
        """Generate S3 key for the file"""
        # Clean file name
        clean_filename = "".join(c for c in file_name if c.isalnum() or c in (' ', '-', '_', '.')).rstrip()
        
        # Create folder structure based on date
        if judgment_date:
            try:
                # Parse date and create year/month structure
                date_parts = judgment_date.split('-')
                if len(date_parts) == 3:
                    day, month, year = date_parts
                    folder_path = f"{year}/{month.zfill(2)}/"
                else:
                    folder_path = "unknown_date/"
            except:
                folder_path = "unknown_date/"
        else:
            folder_path = "unknown_date/"
        
        # Add case number to filename if available
        if case_number:
            clean_case = "".join(c for c in case_number if c.isalnum() or c in ('-', '_'))
            name_parts = clean_filename.rsplit('.', 1)
            if len(name_parts) == 2:
                clean_filename = f"{name_parts[0]}_{clean_case}.{name_parts[1]}"
            else:
                clean_filename = f"{clean_filename}_{clean_case}"
        
        # Combine prefix, folder path, and filename
        s3_key = f"{self.config.folder_prefix}{folder_path}{clean_filename}"
        
        return s3_key
    
    def _get_file_metadata(self, file_path: str) -> Dict[str, Any]:
        """Get file metadata"""
        file_path = Path(file_path)
        
        # Get file stats
        stats = file_path.stat()
        
        # Determine content type
        content_type, _ = mimetypes.guess_type(str(file_path))
        if not content_type:
            content_type = 'application/octet-stream'
        
        # Calculate file hash
        file_hash = self._calculate_file_hash(file_path)
        
        return {
            'size': stats.st_size,
            'content_type': content_type,
            'last_modified': datetime.fromtimestamp(stats.st_mtime).isoformat(),
            'file_hash': file_hash
        }
    
    def _calculate_file_hash(self, file_path: Path) -> str:
        """Calculate MD5 hash of file"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    
    def upload_file(self, 
                   file_path: str, 
                   judgment_date: str = None, 
                   case_number: str = None,
                   metadata: Dict[str, str] = None) -> Optional[Dict[str, Any]]:
        """Upload a file to S3"""
        try:
            file_path = Path(file_path)
            
            if not file_path.exists():
                logger.error(f"File not found: {file_path}")
                return None
            
            # Ensure bucket exists
            if not self._ensure_bucket_exists():
                return None
            
            # Generate S3 key
            s3_key = self._generate_s3_key(file_path.name, judgment_date, case_number)
            
            # Get file metadata
            file_metadata = self._get_file_metadata(file_path)
            
            # Prepare upload metadata
            upload_metadata = {
                'uploaded_by': 'supreme_court_scraper',
                'upload_date': datetime.utcnow().isoformat(),
                'original_filename': file_path.name,
                'file_hash': file_metadata['file_hash'],
                'file_size': str(file_metadata['size'])
            }
            
            if judgment_date:
                upload_metadata['judgment_date'] = judgment_date
            if case_number:
                upload_metadata['case_number'] = case_number
            if metadata:
                upload_metadata.update(metadata)
            
            # Check if file already exists
            if self._file_exists(s3_key):
                logger.warning(f"File already exists in S3: {s3_key}")
                return self._get_file_info(s3_key)
            
            # Upload file with progress
            logger.info(f"Uploading {file_path.name} to S3: {s3_key}")
            
            # For large files, use multipart upload
            file_size = file_metadata['size']
            if file_size > 100 * 1024 * 1024:  # 100MB
                return self._upload_large_file(file_path, s3_key, upload_metadata, file_metadata)
            else:
                return self._upload_small_file(file_path, s3_key, upload_metadata, file_metadata)
            
        except Exception as e:
            logger.error(f"Failed to upload file {file_path}: {e}")
            return None
    
    def _upload_small_file(self, file_path: Path, s3_key: str, metadata: Dict[str, str], file_metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Upload small file in single request"""
        try:
            with open(file_path, 'rb') as f:
                self.s3_client.upload_fileobj(
                    f,
                    self.config.bucket_name,
                    s3_key,
                    ExtraArgs={
                        'ContentType': file_metadata['content_type'],
                        'Metadata': metadata
                    }
                )
            
            logger.info(f"Successfully uploaded: {s3_key}")
            return self._get_file_info(s3_key)
            
        except Exception as e:
            logger.error(f"Failed to upload small file: {e}")
            raise
    
    def _upload_large_file(self, file_path: Path, s3_key: str, metadata: Dict[str, str], file_metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Upload large file with multipart upload and progress tracking"""
        try:
            file_size = file_metadata['size']
            
            # Use boto3's managed transfer with progress callback
            def progress_callback(bytes_transferred):
                percentage = (bytes_transferred / file_size) * 100
                logger.info(f"Upload progress: {percentage:.1f}% ({bytes_transferred}/{file_size} bytes)")
            
            # Configure transfer
            transfer_config = boto3.s3.transfer.TransferConfig(
                multipart_threshold=1024 * 25,  # 25MB
                max_concurrency=10,
                multipart_chunksize=1024 * 25,
                use_threads=True
            )
            
            # Upload with progress tracking
            self.s3_client.upload_file(
                str(file_path),
                self.config.bucket_name,
                s3_key,
                ExtraArgs={
                    'ContentType': file_metadata['content_type'],
                    'Metadata': metadata
                },
                Config=transfer_config,
                Callback=progress_callback
            )
            
            logger.info(f"Successfully uploaded large file: {s3_key}")
            return self._get_file_info(s3_key)
            
        except Exception as e:
            logger.error(f"Failed to upload large file: {e}")
            raise
    
    def _file_exists(self, s3_key: str) -> bool:
        """Check if file exists in S3"""
        try:
            self.s3_client.head_object(Bucket=self.config.bucket_name, Key=s3_key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            raise
    
    def _get_file_info(self, s3_key: str) -> Dict[str, Any]:
        """Get file information from S3"""
        try:
            response = self.s3_client.head_object(Bucket=self.config.bucket_name, Key=s3_key)
            
            # Generate public URL
            s3_url = f"https://{self.config.bucket_name}.s3.{self.config.aws_region}.amazonaws.com/{s3_key}"
            
            return {
                'bucket': self.config.bucket_name,
                'key': s3_key,
                'url': s3_url,
                'size': response['ContentLength'],
                'last_modified': response['LastModified'].isoformat(),
                'etag': response['ETag'].strip('"'),
                'content_type': response.get('ContentType', 'application/octet-stream'),
                'metadata': response.get('Metadata', {})
            }
            
        except Exception as e:
            logger.error(f"Failed to get file info for {s3_key}: {e}")
            return {}
    
    def download_file(self, s3_key: str, local_path: str) -> bool:
        """Download file from S3"""
        try:
            self.s3_client.download_file(
                self.config.bucket_name,
                s3_key,
                local_path
            )
            logger.info(f"Downloaded {s3_key} to {local_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to download {s3_key}: {e}")
            return False
    
    def delete_file(self, s3_key: str) -> bool:
        """Delete file from S3"""
        try:
            self.s3_client.delete_object(
                Bucket=self.config.bucket_name,
                Key=s3_key
            )
            logger.info(f"Deleted {s3_key} from S3")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete {s3_key}: {e}")
            return False
    
    def list_files(self, prefix: str = None, max_keys: int = 1000) -> List[Dict[str, Any]]:
        """List files in S3 bucket"""
        try:
            kwargs = {
                'Bucket': self.config.bucket_name,
                'MaxKeys': max_keys
            }
            
            if prefix:
                kwargs['Prefix'] = prefix
            
            response = self.s3_client.list_objects_v2(**kwargs)
            
            files = []
            for obj in response.get('Contents', []):
                files.append({
                    'key': obj['Key'],
                    'size': obj['Size'],
                    'last_modified': obj['LastModified'].isoformat(),
                    'etag': obj['ETag'].strip('"')
                })
            
            return files
            
        except Exception as e:
            logger.error(f"Failed to list files: {e}")
            return []
    
    def get_storage_stats(self) -> Dict[str, Any]:
        """Get storage statistics"""
        try:
            files = self.list_files(prefix=self.config.folder_prefix)
            
            total_size = sum(f['size'] for f in files)
            total_files = len(files)
            
            # Convert size to human readable format
            def format_size(size_bytes):
                if size_bytes == 0:
                    return "0B"
                size_names = ["B", "KB", "MB", "GB", "TB"]
                i = int(math.floor(math.log(size_bytes, 1024)))
                p = math.pow(1024, i)
                s = round(size_bytes / p, 2)
                return f"{s} {size_names[i]}"
            
            return {
                'total_files': total_files,
                'total_size_bytes': total_size,
                'total_size_formatted': format_size(total_size),
                'bucket_name': self.config.bucket_name,
                'folder_prefix': self.config.folder_prefix
            }
            
        except Exception as e:
            logger.error(f"Failed to get storage stats: {e}")
            return {}

# Example usage
if __name__ == "__main__":
    from config import config
    
    # Test S3 client
    try:
        s3_client = S3Client(config.s3)
        
        # Get storage stats
        stats = s3_client.get_storage_stats()
        print(f"Storage stats: {stats}")
        
        # List some files
        files = s3_client.list_files(max_keys=10)
        print(f"Found {len(files)} files")
        
    except Exception as e:
        print(f"S3 test failed: {e}")