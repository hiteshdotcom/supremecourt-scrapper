#!/usr/bin/env python3
"""
Supreme Court Judgment Scraper - Main Execution Script

This script provides a command-line interface to run the Supreme Court judgment scraper
with various configuration options and modes.

Usage:
    python main.py --help
    python main.py --config config.yaml
    python main.py --start-year 2020 --end-year 2024
    python main.py --resume
    python main.py --stats
"""

import argparse
import sys
import os
from pathlib import Path
from datetime import datetime
import signal
from typing import Optional

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger
from config import AppConfig, config
from supreme_court_scraper import SupremeCourtScraper
from mongodb_client import MongoDBClient
from s3_client import S3Client
from date_manager import DateManager

class ScraperCLI:
    """Command-line interface for the Supreme Court scraper"""
    
    def __init__(self):
        self.scraper: Optional[SupremeCourtScraper] = None
        self.interrupted = False
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle interrupt signals for graceful shutdown"""
        logger.warning(f"Received signal {signum}. Initiating graceful shutdown...")
        self.interrupted = True
        
        if self.scraper:
            logger.info("Cleaning up scraper resources...")
            try:
                self.scraper.cleanup_browser()
                self.scraper.mongo_client.close()
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")
        
        logger.info("Shutdown complete.")
        sys.exit(0)
    
    def setup_logging(self, log_level: str = "INFO", log_file: Optional[str] = None):
        """Setup logging configuration"""
        # Remove default logger
        logger.remove()
        
        # Add console logger
        logger.add(
            sys.stderr,
            level=log_level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        )
        
        # Add file logger if specified
        if log_file:
            logger.add(
                log_file,
                level=log_level,
                format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
                rotation="10 MB",
                retention="30 days"
            )
    
    def validate_environment(self) -> bool:
        """Validate that all required environment variables and dependencies are set"""
        logger.info("Validating environment...")
        
        # Check if .env file exists
        env_file = Path(".env")
        if not env_file.exists():
            logger.error(".env file not found. Please copy .env.template to .env and configure it.")
            return False
        
        # Validate configuration
        if not config.validate():
            logger.error("Configuration validation failed. Please check your .env file.")
            return False
        
        # Test MongoDB connection
        try:
            mongo_client = MongoDBClient(config.mongo)
            mongo_client.close()
            logger.info("MongoDB connection: OK")
        except Exception as e:
            logger.error(f"MongoDB connection failed: {e}")
            return False
        
        # Test S3 connection
        try:
            s3_client = S3Client(config.s3)
            s3_client._ensure_bucket_exists()
            logger.info("S3 connection: OK")
        except Exception as e:
            logger.error(f"S3 connection failed: {e}")
            return False
        
        logger.info("Environment validation: PASSED")
        return True
    
    def show_statistics(self):
        """Show current scraping statistics"""
        try:
            mongo_client = MongoDBClient(config.mongo)
            s3_client = S3Client(config.s3)
            date_manager = DateManager(
                config.scraping.start_year,
                config.scraping.end_year,
                config.scraping.max_date_range_days
            )
            
            print("\n" + "="*60)
            print("SUPREME COURT SCRAPER - CURRENT STATISTICS")
            print("="*60)
            
            # Database statistics
            db_stats = mongo_client.get_statistics()
            print("\nDatabase Statistics:")
            for key, value in db_stats.items():
                print(f"  {key}: {value}")
            
            # S3 statistics
            s3_stats = s3_client.get_storage_stats()
            print("\nS3 Storage Statistics:")
            for key, value in s3_stats.items():
                print(f"  {key}: {value}")
            
            # Progress statistics
            progress_summary = date_manager.get_progress_summary()
            print("\nProgress Statistics:")
            for key, value in progress_summary.items():
                print(f"  {key}: {value}")
            
            print("="*60)
            
            mongo_client.close()
            
        except Exception as e:
            logger.error(f"Failed to retrieve statistics: {e}")
    
    def run_scraper(self, resume: bool = False):
        """Run the main scraper"""
        try:
            logger.info("Initializing Supreme Court judgment scraper...")
            
            # Create scraper instance
            self.scraper = SupremeCourtScraper(config)
            
            if resume:
                logger.info("Resuming from previous session...")
            else:
                logger.info("Starting fresh scraping session...")
            
            # Run scraper
            self.scraper.run()
            
            logger.info("Scraping completed successfully!")
            
        except KeyboardInterrupt:
            logger.warning("Scraping interrupted by user")
        except Exception as e:
            logger.error(f"Scraping failed: {e}")
            raise
        finally:
            if self.scraper:
                self.scraper.cleanup_browser()
                self.scraper.mongo_client.close()
    
    def reset_progress(self):
        """Reset scraping progress (use with caution)"""
        try:
            response = input("Are you sure you want to reset all progress? This will clear the progress file but keep downloaded data. (yes/no): ")
            if response.lower() != 'yes':
                print("Reset cancelled.")
                return
            
            date_manager = DateManager(
                config.scraping.start_year,
                config.scraping.end_year,
                config.scraping.max_date_range_days
            )
            
            # Reset progress file
            progress_file = Path("scraping_progress.json")
            if progress_file.exists():
                progress_file.unlink()
                logger.info("Progress file deleted.")
            
            logger.info("Progress reset completed.")
            
        except Exception as e:
            logger.error(f"Failed to reset progress: {e}")
    
    def test_captcha(self):
        """Test CAPTCHA solving functionality"""
        try:
            logger.info("Testing CAPTCHA solving...")
            
            from captcha_solver import CaptchaSolver
            from playwright.sync_api import sync_playwright
            
            captcha_solver = CaptchaSolver(
                config.captcha.use_manual_input,
                config.captcha.ocr_confidence_threshold
            )
            
            with sync_playwright() as p:
                browser = p.firefox.launch(headless=False)
                page = browser.new_page()
                
                # Navigate to the judgment page
                page.goto(config.scraping.base_url)
                page.wait_for_load_state("networkidle")
                
                # Test CAPTCHA solving
                captcha_text = captcha_solver.solve_captcha(page, 1)
                
                if captcha_text:
                    logger.info(f"CAPTCHA solved: {captcha_text}")
                else:
                    logger.error("Failed to solve CAPTCHA")
                
                browser.close()
            
        except Exception as e:
            logger.error(f"CAPTCHA test failed: {e}")

def create_parser() -> argparse.ArgumentParser:
    """Create command-line argument parser"""
    parser = argparse.ArgumentParser(
        description="Supreme Court Judgment Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                          # Run with default settings
  python main.py --resume                 # Resume from previous session
  python main.py --start-year 2020        # Start from 2020
  python main.py --end-year 2022          # End at 2022
  python main.py --stats                  # Show current statistics
  python main.py --reset-progress         # Reset scraping progress
  python main.py --test-captcha           # Test CAPTCHA solving
  python main.py --log-level DEBUG        # Enable debug logging
        """
    )
    
    # Main actions
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument(
        "--run", action="store_true", default=True,
        help="Run the scraper (default action)"
    )
    action_group.add_argument(
        "--stats", action="store_true",
        help="Show current statistics and exit"
    )
    action_group.add_argument(
        "--reset-progress", action="store_true",
        help="Reset scraping progress"
    )
    action_group.add_argument(
        "--test-captcha", action="store_true",
        help="Test CAPTCHA solving functionality"
    )
    
    # Scraping options
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume from previous session"
    )
    parser.add_argument(
        "--start-year", type=int,
        help="Start year for scraping (overrides config)"
    )
    parser.add_argument(
        "--end-year", type=int,
        help="End year for scraping (overrides config)"
    )
    parser.add_argument(
        "--headless", action="store_true",
        help="Run browser in headless mode"
    )
    parser.add_argument(
        "--no-headless", action="store_true",
        help="Run browser with GUI (for debugging)"
    )
    
    # Logging options
    parser.add_argument(
        "--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO", help="Set logging level"
    )
    parser.add_argument(
        "--log-file", type=str,
        help="Log file path (default: scraper.log)"
    )
    
    # Configuration
    parser.add_argument(
        "--config", type=str,
        help="Path to configuration file"
    )
    parser.add_argument(
        "--env-file", type=str, default=".env",
        help="Path to environment file (default: .env)"
    )
    
    return parser

def main():
    """Main entry point"""
    parser = create_parser()
    args = parser.parse_args()
    
    # Initialize CLI
    cli = ScraperCLI()
    
    # Setup logging
    log_file = args.log_file or config.logging.log_file
    cli.setup_logging(args.log_level, log_file)
    
    logger.info("Supreme Court Judgment Scraper started")
    logger.info(f"Arguments: {vars(args)}")
    
    try:
        # Override configuration with command-line arguments
        if args.start_year:
            config.scraping.start_year = args.start_year
        if args.end_year:
            config.scraping.end_year = args.end_year
        if args.headless:
            config.scraping.headless = True
        if args.no_headless:
            config.scraping.headless = False
        
        # Validate environment (except for stats command)
        if not args.stats and not cli.validate_environment():
            logger.error("Environment validation failed. Exiting.")
            sys.exit(1)
        
        # Execute requested action
        if args.stats:
            cli.show_statistics()
        elif args.reset_progress:
            cli.reset_progress()
        elif args.test_captcha:
            cli.test_captcha()
        else:
            cli.run_scraper(resume=args.resume)
        
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Execution failed: {e}")
        sys.exit(1)
    
    logger.info("Supreme Court Judgment Scraper finished")

if __name__ == "__main__":
    main()