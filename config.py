import os
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

@dataclass
class ScrapingConfig:
    """Configuration for web scraping parameters"""
    base_url: str = "https://www.sci.gov.in/judgements-judgement-date/"
    max_date_range_days: int = 30  # Supreme Court allows max 30 days
    start_year: int = int(os.getenv("SCRAPING_START_YEAR", "2004"))  # Read from environment
    end_year: int = int(os.getenv("SCRAPING_END_YEAR", "2024"))  # Read from environment
    headless: bool = True
    slow_mo: int = 1000  # Milliseconds delay between actions
    timeout: int = 30000  # Page timeout in milliseconds
    max_retries: int = 3
    retry_delay: int = 5  # Seconds
    
@dataclass
class MongoConfig:
    """MongoDB configuration"""
    connection_string: str = os.getenv("MONGO_CONNECTION_STRING", "mongodb://localhost:27017/")
    database_name: str = os.getenv("MONGO_DATABASE", "supreme_court_judgments")
    collection_name: str = os.getenv("MONGO_COLLECTION", "judgments")
    
@dataclass
class S3Config:
    """AWS S3 configuration"""
    aws_access_key_id: str = os.getenv("AWS_ACCESS_KEY_ID", "")
    aws_secret_access_key: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    bucket_name: str = os.getenv("S3_BUCKET_NAME", "supreme-court-judgments")
    folder_prefix: str = os.getenv("S3_FOLDER_PREFIX", "judgments/")
    
    def __post_init__(self):
        """Print configuration values for debugging"""
        print(f"{self.bucket_name} bucket name")
        print(f"{self.folder_prefix} folder prefix")
        print(f"{self.aws_access_key_id} aws access key id")
        print(f"{self.aws_secret_access_key} aws secret access key")
        print(f"{self.aws_region} aws region")

@dataclass
class CaptchaConfig:
    """CAPTCHA solving configuration"""
    use_manual_input: bool = os.getenv("CAPTCHA_USE_MANUAL_INPUT", "true").lower() == "true"
    use_openai: bool = os.getenv("CAPTCHA_USE_OPENAI", "false").lower() == "true"
    ocr_confidence_threshold: float = float(os.getenv("CAPTCHA_OCR_CONFIDENCE_THRESHOLD", "0.7"))
    max_captcha_attempts: int = int(os.getenv("CAPTCHA_MAX_ATTEMPTS", "3"))
    # OpenAI configuration
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    openai_max_tokens: int = int(os.getenv("OPENAI_MAX_TOKENS", "100"))
    openai_temperature: float = float(os.getenv("OPENAI_TEMPERATURE", "0.1"))
    
@dataclass
class LoggingConfig:
    """Logging configuration"""
    log_level: str = "INFO"
    log_file: str = "supreme_court_scraper.log"
    log_format: str = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}"
    
@dataclass
class AppConfig:
    """Main application configuration"""
    scraping: ScrapingConfig = field(default_factory=ScrapingConfig)
    mongo: MongoConfig = field(default_factory=MongoConfig)
    s3: S3Config = field(default_factory=S3Config)
    captcha: CaptchaConfig = field(default_factory=CaptchaConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    
    # Progress tracking
    progress_file: str = "scraping_progress.json"
    resume_on_restart: bool = True
    
    def validate(self) -> bool:
        """Validate configuration"""
        errors = []
        
        # Check MongoDB connection string
        if not self.mongo.connection_string:
            errors.append("MongoDB connection string is required")
            
        # Check S3 credentials
        if not self.s3.aws_access_key_id or not self.s3.aws_secret_access_key:
            errors.append("AWS credentials are required for S3 upload")
            
        if not self.s3.bucket_name:
            errors.append("S3 bucket name is required")
            
        # Check date range
        if self.scraping.start_year >= self.scraping.end_year:
            errors.append("Start year must be less than end year")
            
        # Check OpenAI configuration if enabled
        if self.captcha.use_openai and not self.captcha.openai_api_key:
            errors.append("OpenAI API key is required when use_openai is enabled")
            
        if errors:
            print("Configuration errors:")
            for error in errors:
                print(f"  - {error}")
            return False
            
        return True

# Global configuration instance
config = AppConfig()