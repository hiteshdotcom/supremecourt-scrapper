# Supreme Court Judgment Scraper

An automated tool to download 20 years of Supreme Court judgment data from `https://www.sci.gov.in/judgements-judgement-date/`, store metadata in MongoDB, and upload files to AWS S3.

## Features

- **Automated Web Scraping**: Uses Playwright to navigate and interact with the Supreme Court website
- **CAPTCHA Handling**: Supports both OCR-based and manual CAPTCHA solving
- **Date Range Management**: Automatically splits 20 years into 30-day chunks for efficient processing
- **MongoDB Integration**: Stores judgment metadata with comprehensive indexing
- **S3 Upload**: Automatically uploads downloaded files to AWS S3 with organized folder structure
- **Progress Tracking**: Resume capability with detailed progress tracking
- **Error Handling**: Comprehensive retry logic and error recovery
- **Command-Line Interface**: Easy-to-use CLI with multiple operation modes

## Prerequisites

- Python 3.8 or higher
- MongoDB instance (local or cloud)
- AWS S3 bucket and credentials
- Tesseract OCR (for automatic CAPTCHA solving)

## Installation

1. **Clone or download the project files**

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Install Playwright browsers**:
   ```bash
   playwright install firefox
   ```

4. **Install Tesseract OCR** (optional, for automatic CAPTCHA solving):
   
   **macOS**:
   ```bash
   brew install tesseract
   ```
   
   **Ubuntu/Debian**:
   ```bash
   sudo apt-get install tesseract-ocr
   ```
   
   **Windows**:
   Download from: https://github.com/UB-Mannheim/tesseract/wiki

## Configuration

1. **Copy the environment template**:
   ```bash
   cp .env.template .env
   ```

2. **Edit the `.env` file** with your actual configuration:

### Required Configuration

```env
# MongoDB Configuration
MONGO_CONNECTION_STRING=mongodb://localhost:27017/
MONGO_DATABASE=supreme_court_judgments

# AWS S3 Configuration
AWS_ACCESS_KEY_ID=your_aws_access_key_here
AWS_SECRET_ACCESS_KEY=your_aws_secret_key_here
AWS_REGION=us-east-1
S3_BUCKET_NAME=your-s3-bucket-name

# Date Range
SCRAPING_START_YEAR=2004
SCRAPING_END_YEAR=2024
```

### Optional Configuration

```env
# CAPTCHA Settings
CAPTCHA_USE_MANUAL_INPUT=true  # Set to false for automatic OCR
CAPTCHA_OCR_CONFIDENCE_THRESHOLD=0.7

# Browser Settings
SCRAPING_HEADLESS=true  # Set to false to see browser window
SCRAPING_SLOW_MO=1000   # Delay between actions (ms)

# Logging
LOG_LEVEL=INFO
LOG_FILE=scraper.log
```

## Usage

### Basic Usage

```bash
# Run with default settings
python main.py

# Run with custom date range
python main.py --start-year 2020 --end-year 2024

# Resume from previous session
python main.py --resume

# Run with browser visible (for debugging)
python main.py --no-headless
```

### Statistics and Monitoring

```bash
# Show current statistics
python main.py --stats

# Test CAPTCHA solving
python main.py --test-captcha

# Reset progress (use with caution)
python main.py --reset-progress
```

### Advanced Options

```bash
# Enable debug logging
python main.py --log-level DEBUG

# Custom log file
python main.py --log-file custom.log

# Show help
python main.py --help
```

## Project Structure

```
├── main.py                    # Main execution script with CLI
├── supreme_court_scraper.py   # Core scraper class
├── config.py                  # Configuration management
├── date_manager.py            # Date range management
├── captcha_solver.py          # CAPTCHA handling
├── mongodb_client.py          # MongoDB integration
├── s3_client.py              # AWS S3 integration
├── requirements.txt           # Python dependencies
├── .env.template             # Environment configuration template
├── .env                      # Your actual configuration (create this)
├── pw_CAPTCHA.py             # Legacy CAPTCHA example
├── pw_quickstart.py          # Legacy Playwright example
└── README.md                 # This file
```

## Data Schema

### MongoDB Document Structure

```json
{
  "_id": "unique_judgment_id",
  "title": "Judgment title",
  "case_number": "Case number",
  "diary_no": "Diary number",
  "judge": "Judge name",
  "judgment_date": "DD-MM-YYYY",
  "file_url": "Original download URL",
  "file_name": "downloaded_file.pdf",
  "file_size": 1234567,
  "file_type": "pdf",
  "s3_bucket": "bucket-name",
  "s3_key": "path/to/file.pdf",
  "s3_url": "https://s3.amazonaws.com/...",
  "processing_status": "completed",
  "error_message": null,
  "search_from_date": "01-01-2020",
  "search_to_date": "31-01-2020",
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

### S3 Folder Structure

```
s3://your-bucket/supreme-court-judgments/
├── 2020/
│   ├── 01/  # January
│   │   ├── judgment_case123_2020.pdf
│   │   └── judgment_case456_2020.pdf
│   └── 02/  # February
├── 2021/
└── ...
```

## How It Works

1. **Date Range Generation**: The scraper splits the specified year range into 30-day chunks to comply with the website's limitations.

2. **Web Navigation**: Uses Playwright to navigate to the Supreme Court website and fill the search form.

3. **CAPTCHA Solving**: 
   - **Manual Mode**: Displays the CAPTCHA and waits for user input
   - **OCR Mode**: Uses Tesseract to automatically read the CAPTCHA

4. **Data Extraction**: Parses the search results to extract judgment links and metadata.

5. **File Download**: Downloads each judgment PDF file.

6. **Database Storage**: Stores metadata in MongoDB with proper indexing.

7. **S3 Upload**: Uploads files to S3 with organized folder structure.

8. **Progress Tracking**: Saves progress to allow resuming interrupted sessions.

## Troubleshooting

### Common Issues

1. **CAPTCHA Failures**:
   - Set `CAPTCHA_USE_MANUAL_INPUT=true` for manual solving
   - Ensure Tesseract is properly installed for OCR
   - Adjust `CAPTCHA_OCR_CONFIDENCE_THRESHOLD`

2. **MongoDB Connection Issues**:
   - Verify MongoDB is running
   - Check connection string format
   - Ensure database permissions

3. **S3 Upload Failures**:
   - Verify AWS credentials
   - Check bucket permissions
   - Ensure bucket exists in specified region

4. **Browser Issues**:
   - Run `playwright install firefox` to reinstall browser
   - Try running with `--no-headless` to see what's happening
   - Check for system-specific Playwright issues

### Debugging

```bash
# Enable debug logging
python main.py --log-level DEBUG

# Run with visible browser
python main.py --no-headless

# Test individual components
python main.py --test-captcha
python main.py --stats
```

### Performance Optimization

1. **Adjust timeouts** in `.env` file
2. **Modify retry delays** for your network conditions
3. **Use headless mode** for better performance
4. **Monitor system resources** during large scraping sessions

## Security Considerations

- Never commit your `.env` file to version control
- Use IAM roles with minimal required permissions for S3
- Consider using MongoDB authentication in production
- Regularly rotate AWS credentials

## Legal and Ethical Considerations

- This tool is designed for legitimate research and archival purposes
- Respect the Supreme Court website's terms of service
- Implement appropriate delays to avoid overloading the server
- Consider the website's robots.txt file
- Use responsibly and in compliance with applicable laws

## What You Need to Provide

To use this automation tool, you need to provide the following:

### 1. MongoDB Setup
- **MongoDB Connection String**: Either a local MongoDB instance (`mongodb://localhost:27017/`) or a cloud MongoDB URI (MongoDB Atlas)
- **Database Name**: Name for your judgment database (e.g., `supreme_court_judgments`)

### 2. AWS S3 Configuration
- **AWS Access Key ID**: Your AWS access key
- **AWS Secret Access Key**: Your AWS secret key
- **S3 Bucket Name**: Name of your S3 bucket where files will be stored
- **AWS Region**: The region where your S3 bucket is located (e.g., `us-east-1`)

### 3. Date Range (Optional)
- **Start Year**: The year to start scraping from (default: 2004)
- **End Year**: The year to end scraping at (default: 2024)

### 4. CAPTCHA Handling Preference
- **Manual vs Automatic**: Choose whether you want to solve CAPTCHAs manually or use OCR
- **Tesseract Installation**: If using automatic CAPTCHA solving, install Tesseract OCR

### 5. System Requirements
- **Python 3.8+**: Ensure you have Python installed
- **Internet Connection**: Stable internet for downloading judgments
- **Storage Space**: Adequate disk space for temporary file storage

## Getting Started Checklist

- [ ] Install Python dependencies (`pip install -r requirements.txt`)
- [ ] Install Playwright browsers (`playwright install firefox`)
- [ ] Set up MongoDB (local or cloud)
- [ ] Create AWS S3 bucket
- [ ] Copy `.env.template` to `.env`
- [ ] Fill in your configuration in `.env`
- [ ] Verify installation (`python verify_setup.py`)
- [ ] Test the setup (`python main.py --stats`)
- [ ] Run the scraper (`python main.py`)

### Verification Script

A verification script is included to check your setup:

```bash
python verify_setup.py
```

This script will check all dependencies and confirm your setup is ready.

## Contributing

To contribute to this project:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is provided as-is for educational and research purposes. Please ensure compliance with all applicable laws and terms of service when using this tool.

## Support

For issues and questions:

1. Check the troubleshooting section above
2. Review the logs for error details
3. Test individual components using the CLI options
4. Create an issue with detailed error information

---

**Note**: This tool interacts with a government website. Please use it responsibly and in accordance with the website's terms of service and applicable laws.




