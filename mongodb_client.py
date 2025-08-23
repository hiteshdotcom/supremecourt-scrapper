from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import ConnectionFailure, DuplicateKeyError, PyMongoError
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import hashlib
from loguru import logger
from config import MongoConfig

@dataclass
class JudgmentMetadata:
    """Data class for judgment metadata"""
    judgment_id: str  # Generated hash
    
    # Court hierarchy information
    court_type: str = "supreme_court"  # supreme_court, high_court, district_court, tribunal
    court_level: int = 1  # 1=Supreme, 2=High, 3=District, 4=Tribunal
    court_name: Optional[str] = None  # Specific court name (e.g., "Delhi High Court")
    jurisdiction: Optional[str] = None  # State/Region jurisdiction
    
    # Core judgment information from table columns
    serial_number: Optional[str] = None
    diary_number: Optional[str] = None  # Diary Number column
    case_number: Optional[str] = None   # Case Number column
    petitioner_respondent: Optional[str] = None  # Petitioner/Respondent column
    advocate: Optional[str] = None      # Advocate column
    bench: Optional[str] = None         # Bench column
    judgment_by: Optional[str] = None   # Judgment By column
    judgment_date: Optional[str] = None # Judgment column (date)
    
    # Legacy fields for backward compatibility
    diary_no: Optional[str] = None      # Maps to diary_number
    title: Optional[str] = None         # Maps to petitioner_respondent
    judge: Optional[str] = None         # Maps to judgment_by
    
    # File and URL information
    file_url: Optional[str] = None      # Primary PDF download link (legacy)
    pdf_link: Optional[str] = None      # Primary PDF link (legacy)
    pdf_links: Optional[List[str]] = None  # All PDF links found
    judgment_links: Optional[List[str]] = None  # All judgment links as array of strings
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    
    # S3 information
    s3_bucket: Optional[str] = None
    s3_key: Optional[str] = None
    s3_url: Optional[str] = None
    
    # Processing information
    scraped_date: datetime = None
    processing_status: str = "pending"  # pending, downloaded, uploaded, completed, failed
    error_message: Optional[str] = None
    retry_count: int = 0
    
    # Search date range used
    search_from_date: Optional[str] = None
    search_to_date: Optional[str] = None
    
    # Additional metadata
    page_number: Optional[int] = None
    total_pages: Optional[int] = None
    
    def __post_init__(self):
        if self.scraped_date is None:
            self.scraped_date = datetime.utcnow()
        
        # Generate unique ID if not provided
        if not self.judgment_id:
            self.judgment_id = self.generate_id()
    
    def generate_id(self) -> str:
        """Generate unique ID based on judgment details"""
        # Use court type, case number, diary number, and judgment date for uniqueness
        id_string = f"{self.court_type}_{self.case_number or ''}_{self.diary_no or ''}_{self.judgment_date or ''}_{self.judge or ''}"
        return hashlib.md5(id_string.encode()).hexdigest()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MongoDB storage"""
        data = asdict(self)
        # Convert datetime to ISO format
        if isinstance(data['scraped_date'], datetime):
            data['scraped_date'] = data['scraped_date'].isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'JudgmentMetadata':
        """Create from dictionary"""
        # Remove MongoDB's _id field if present
        data = {k: v for k, v in data.items() if k != '_id'}
        
        # Convert ISO string back to datetime
        if isinstance(data.get('scraped_date'), str):
            data['scraped_date'] = datetime.fromisoformat(data['scraped_date'])
        return cls(**data)

class MongoDBClient:
    """MongoDB client for Supreme Court judgments"""
    
    def __init__(self, config: MongoConfig):
        self.config = config
        self.client = None
        self.db = None
        self.collection = None
        self._connect()
    
    def _connect(self):
        """Establish MongoDB connection"""
        try:
            # Configure SSL settings for MongoDB Atlas
            connection_params = {
                'serverSelectionTimeoutMS': 5000,
                'tlsAllowInvalidCertificates': True,  # Allow invalid certificates
            }
            
            self.client = MongoClient(self.config.connection_string, **connection_params)
            
            # Test connection
            self.client.admin.command('ping')
            
            self.db = self.client[self.config.database_name]
            self.collection = self.db[self.config.collection_name]
            
            # Create indexes
            self._create_indexes()
            
            logger.info(f"Connected to MongoDB: {self.config.database_name}.{self.config.collection_name}")
            
        except ConnectionFailure as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
        except Exception as e:
            logger.error(f"MongoDB connection error: {e}")
            raise
    
    def _create_indexes(self):
        """Create necessary indexes for efficient querying"""
        try:
            # Unique index on judgment_id
            self.collection.create_index("judgment_id", unique=True)
            
            # Court hierarchy indexes
            self.collection.create_index("court_type")
            self.collection.create_index("court_level")
            self.collection.create_index([
                ("court_type", ASCENDING),
                ("court_level", ASCENDING)
            ])
            
            # Compound indexes for common queries
            self.collection.create_index([
                ("court_type", ASCENDING),
                ("case_number", ASCENDING),
                ("judgment_date", ASCENDING)
            ])
            
            self.collection.create_index([
                ("processing_status", ASCENDING),
                ("scraped_date", DESCENDING)
            ])
            
            self.collection.create_index([
                ("search_from_date", ASCENDING),
                ("search_to_date", ASCENDING)
            ])
            
            # Text index for search
            self.collection.create_index([
                ("title", "text"),
                ("judge", "text"),
                ("case_number", "text"),
                ("court_name", "text")
            ])
            
            logger.info("MongoDB indexes created successfully")
            
        except Exception as e:
            logger.warning(f"Failed to create some indexes: {e}")
    
    def insert_judgment(self, judgment: JudgmentMetadata) -> bool:
        """Insert a new judgment record"""
        try:
            result = self.collection.insert_one(judgment.to_dict())
            logger.info(f"Inserted judgment: {judgment.judgment_id}")
            return True
            
        except DuplicateKeyError:
            logger.warning(f"Judgment already exists: {judgment.judgment_id}")
            return False
        except Exception as e:
            logger.error(f"Failed to insert judgment {judgment.judgment_id}: {e}")
            return False
    
    def update_judgment(self, judgment_id: str, updates: Dict[str, Any]) -> bool:
        """Update an existing judgment record"""
        try:
            # Add update timestamp
            updates['last_updated'] = datetime.utcnow().isoformat()
            
            result = self.collection.update_one(
                {"judgment_id": judgment_id},
                {"$set": updates}
            )
            
            if result.modified_count > 0:
                logger.info(f"Updated judgment: {judgment_id}")
                return True
            else:
                logger.warning(f"No judgment found to update: {judgment_id}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to update judgment {judgment_id}: {e}")
            return False
    
    def get_judgment(self, judgment_id: str) -> Optional[JudgmentMetadata]:
        """Get a judgment by ID"""
        try:
            doc = self.collection.find_one({"judgment_id": judgment_id})
            if doc:
                return JudgmentMetadata.from_dict(doc)
            return None
            
        except Exception as e:
            logger.error(f"Failed to get judgment {judgment_id}: {e}")
            return None
    
    def get_judgments_by_status(self, status: str, limit: int = 100) -> List[JudgmentMetadata]:
        """Get judgments by processing status"""
        try:
            cursor = self.collection.find(
                {"processing_status": status}
            ).limit(limit)
            
            return [JudgmentMetadata.from_dict(doc) for doc in cursor]
            
        except Exception as e:
            logger.error(f"Failed to get judgments by status {status}: {e}")
            return []
    
    def get_judgments_by_date_range(self, from_date: str, to_date: str) -> List[JudgmentMetadata]:
        """Get judgments by search date range"""
        try:
            cursor = self.collection.find({
                "search_from_date": from_date,
                "search_to_date": to_date
            })
            
            return [JudgmentMetadata.from_dict(doc) for doc in cursor]
            
        except Exception as e:
            logger.error(f"Failed to get judgments for date range {from_date} to {to_date}: {e}")
            return []
    
    def get_judgments_by_court_type(self, court_type: str, limit: int = 100) -> List[JudgmentMetadata]:
        """Get judgments by court type"""
        try:
            cursor = self.collection.find({"court_type": court_type}).limit(limit)
            return [JudgmentMetadata.from_dict(doc) for doc in cursor]
            
        except Exception as e:
            logger.error(f"Failed to get judgments by court type: {e}")
            return []
    
    def get_judgments_by_court_level(self, court_level: int, limit: int = 100) -> List[JudgmentMetadata]:
        """Get judgments by court level"""
        try:
            cursor = self.collection.find({"court_level": court_level}).limit(limit)
            return [JudgmentMetadata.from_dict(doc) for doc in cursor]
            
        except Exception as e:
            logger.error(f"Failed to get judgments by court level: {e}")
            return []
    
    def get_judgments_by_court_and_status(self, court_type: str, status: str, limit: int = 100) -> List[JudgmentMetadata]:
        """Get judgments by court type and processing status"""
        try:
            cursor = self.collection.find({
                "court_type": court_type,
                "processing_status": status
            }).limit(limit)
            return [JudgmentMetadata.from_dict(doc) for doc in cursor]
            
        except Exception as e:
            logger.error(f"Failed to get judgments by court and status: {e}")
            return []
    
    def mark_as_downloaded(self, judgment_id: str, file_info: Dict[str, Any]) -> bool:
        """Mark judgment as downloaded with file information"""
        updates = {
            "processing_status": "downloaded",
            "file_name": file_info.get("file_name"),
            "file_size": file_info.get("file_size"),
            "file_type": file_info.get("file_type"),
            "downloaded_date": datetime.utcnow().isoformat()
        }
        return self.update_judgment(judgment_id, updates)
    
    def mark_as_uploaded(self, judgment_id: str, s3_info: Dict[str, Any]) -> bool:
        """Mark judgment as uploaded to S3"""
        updates = {
            "processing_status": "uploaded",
            "s3_bucket": s3_info.get("bucket"),
            "s3_key": s3_info.get("key"),
            "s3_url": s3_info.get("url"),
            "uploaded_date": datetime.utcnow().isoformat()
        }
        return self.update_judgment(judgment_id, updates)
    
    def mark_as_completed(self, judgment_id: str) -> bool:
        """Mark judgment as completed"""
        updates = {
            "processing_status": "completed",
            "completed_date": datetime.utcnow().isoformat()
        }
        return self.update_judgment(judgment_id, updates)
    
    def mark_as_failed(self, judgment_id: str, error_message: str) -> bool:
        """Mark judgment as failed with error message"""
        # Increment retry count
        judgment = self.get_judgment(judgment_id)
        retry_count = judgment.retry_count + 1 if judgment else 1
        
        updates = {
            "processing_status": "failed",
            "error_message": error_message,
            "retry_count": retry_count,
            "failed_date": datetime.utcnow().isoformat()
        }
        return self.update_judgment(judgment_id, updates)
    
    def judgment_exists(self, judgment_id: str) -> bool:
        """Check if judgment already exists in database"""
        try:
            return self.collection.count_documents({"judgment_id": judgment_id}) > 0
        except Exception as e:
            logger.error(f"Error checking judgment existence: {e}")
            return False
    
    def find_duplicate_by_content(self, diary_no: str, case_number: str, judgment_date: str) -> Optional[str]:
        """Find duplicate judgment by content fields"""
        try:
            query = {
                "diary_no": diary_no,
                "case_number": case_number,
                "judgment_date": judgment_date
            }
            # Remove None values from query
            query = {k: v for k, v in query.items() if v is not None}
            
            existing = self.collection.find_one(query)
            return existing.get("judgment_id") if existing else None
        except Exception as e:
            logger.error(f"Error finding duplicate judgment: {e}")
            return None
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get processing statistics"""
        try:
            # Status breakdown
            status_pipeline = [
                {
                    "$group": {
                        "_id": "$processing_status",
                        "count": {"$sum": 1}
                    }
                }
            ]
            
            # Court type breakdown
            court_type_pipeline = [
                {
                    "$group": {
                        "_id": "$court_type",
                        "count": {"$sum": 1}
                    }
                }
            ]
            
            # Court level breakdown
            court_level_pipeline = [
                {
                    "$group": {
                        "_id": "$court_level",
                        "count": {"$sum": 1}
                    }
                }
            ]
            
            status_counts = {doc["_id"]: doc["count"] for doc in self.collection.aggregate(status_pipeline)}
            court_type_counts = {doc["_id"]: doc["count"] for doc in self.collection.aggregate(court_type_pipeline)}
            court_level_counts = {doc["_id"]: doc["count"] for doc in self.collection.aggregate(court_level_pipeline)}
            
            total_count = self.collection.count_documents({})
            
            # Get date range of scraped data
            earliest = self.collection.find_one(
                {}, 
                sort=[("scraped_date", ASCENDING)]
            )
            latest = self.collection.find_one(
                {}, 
                sort=[("scraped_date", DESCENDING)]
            )
            
            return {
                "total_judgments": total_count,
                "status_breakdown": status_counts,
                "court_type_breakdown": court_type_counts,
                "court_level_breakdown": court_level_counts,
                "earliest_scraped": earliest.get("scraped_date") if earliest else None,
                "latest_scraped": latest.get("scraped_date") if latest else None,
                "completion_rate": (
                    status_counts.get("completed", 0) / total_count * 100 
                    if total_count > 0 else 0
                )
            }
            
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}
    
    def cleanup_failed_records(self, max_retries: int = 3) -> int:
        """Remove records that have failed too many times"""
        try:
            result = self.collection.delete_many({
                "processing_status": "failed",
                "retry_count": {"$gte": max_retries}
            })
            
            logger.info(f"Cleaned up {result.deleted_count} failed records")
            return result.deleted_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup records: {e}")
            return 0
    
    def close(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed")

# Example usage
if __name__ == "__main__":
    from config import config
    
    # Test MongoDB client
    try:
        mongo_client = MongoDBClient(config.mongo)
        
        # Test judgment creation
        test_judgment = JudgmentMetadata(
            judgment_id="test_001",
            case_number="TEST/2024/001",
            title="Test Judgment",
            judge="Test Judge",
            judgment_date="01-01-2024"
        )
        
        # Insert test judgment
        success = mongo_client.insert_judgment(test_judgment)
        print(f"Insert success: {success}")
        
        # Get statistics
        stats = mongo_client.get_statistics()
        print(f"Statistics: {stats}")
        
        mongo_client.close()
        
    except Exception as e:
        print(f"MongoDB test failed: {e}")