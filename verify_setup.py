#!/usr/bin/env python3
"""
Setup Verification Script for Supreme Court Judgment Scraper

This script verifies that all dependencies are properly installed
and the application is ready to run.
"""

import sys
import importlib
from pathlib import Path

def check_python_version():
    """Check if Python version is compatible"""
    print("\n🐍 Checking Python version...")
    version = sys.version_info
    print(f"   Python {version.major}.{version.minor}.{version.micro}")
    
    if version.major == 3 and version.minor >= 8:
        print("   ✅ Python version is compatible")
        return True
    else:
        print("   ❌ Python 3.8+ required")
        return False

def check_dependencies():
    """Check if all required dependencies are installed"""
    print("\n📦 Checking dependencies...")
    
    required_packages = [
        'playwright',
        'requests', 
        'bs4',  # beautifulsoup4
        'lxml',
        'pytesseract',
        'PIL',  # Pillow
        'cv2',  # opencv-python
        'pymongo',
        'boto3',
        'numpy',
        'dotenv',  # python-dotenv
        'yaml',  # pyyaml
        'loguru',
        'tqdm'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            importlib.import_module(package)
            print(f"   ✅ {package}")
        except ImportError:
            print(f"   ❌ {package} - NOT FOUND")
            missing_packages.append(package)
    
    if missing_packages:
        print(f"\n   Missing packages: {', '.join(missing_packages)}")
        print("   Run: pip install -r requirements.txt")
        return False
    
    print("   ✅ All dependencies installed")
    return True

def check_playwright_browsers():
    """Check if Playwright browsers are installed"""
    print("\n🌐 Checking Playwright browsers...")
    
    try:
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            # Try to launch chromium
            browser = p.chromium.launch(headless=True)
            browser.close()
            print("   ✅ Playwright browsers installed")
            return True
    except Exception as e:
        print(f"   ❌ Playwright browsers not found: {e}")
        print("   Run: playwright install")
        return False

def check_project_files():
    """Check if all project files exist"""
    print("\n📁 Checking project files...")
    
    required_files = [
        'supreme_court_scraper.py',
        'config.py',
        'date_manager.py',
        'captcha_solver.py',
        'mongodb_client.py',
        's3_client.py',
        'main.py',
        'requirements.txt',
        '.env.template'
    ]
    
    missing_files = []
    
    for file in required_files:
        if Path(file).exists():
            print(f"   ✅ {file}")
        else:
            print(f"   ❌ {file} - NOT FOUND")
            missing_files.append(file)
    
    if missing_files:
        print(f"\n   Missing files: {', '.join(missing_files)}")
        return False
    
    print("   ✅ All project files present")
    return True

def check_configuration():
    """Check configuration setup"""
    print("\n⚙️  Checking configuration...")
    
    env_file = Path('.env')
    if env_file.exists():
        print("   ✅ .env file exists")
        
        # Check if basic config can be loaded
        try:
            from config import config
            print("   ✅ Configuration loaded successfully")
            return True
        except Exception as e:
            print(f"   ❌ Configuration error: {e}")
            return False
    else:
        print("   ⚠️  .env file not found")
        print("   Copy .env.template to .env and configure your settings")
        return False

def check_application_import():
    """Check if main application can be imported"""
    print("\n🚀 Checking application import...")
    
    try:
        from supreme_court_scraper import SupremeCourtScraper
        print("   ✅ Supreme Court Scraper imported successfully")
        return True
    except Exception as e:
        print(f"   ❌ Import error: {e}")
        return False

def main():
    """Run all verification checks"""
    print("="*60)
    print("SUPREME COURT JUDGMENT SCRAPER - SETUP VERIFICATION")
    print("="*60)
    
    checks = [
        check_python_version,
        check_dependencies,
        check_playwright_browsers,
        check_project_files,
        check_configuration,
        check_application_import
    ]
    
    results = []
    for check in checks:
        results.append(check())
    
    print("\n" + "="*60)
    print("VERIFICATION SUMMARY")
    print("="*60)
    
    passed = sum(results)
    total = len(results)
    
    if passed == total:
        print(f"🎉 All checks passed ({passed}/{total})")
        print("\n✅ Your setup is ready!")
        print("\nNext steps:")
        print("1. Configure your .env file with MongoDB and AWS credentials")
        print("2. Run: python main.py --stats (to verify connections)")
        print("3. Run: python main.py --test-captcha (to test CAPTCHA solving)")
        print("4. Run: python main.py --run (to start scraping)")
    else:
        print(f"❌ {total - passed} checks failed ({passed}/{total} passed)")
        print("\nPlease fix the issues above before running the scraper.")
    
    print("\n" + "="*60)
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)