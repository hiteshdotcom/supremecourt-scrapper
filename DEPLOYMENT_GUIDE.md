# Supreme Court Scraper - Deployment Guide

This guide covers how to deploy and run the Supreme Court judgment scraping tool in various environments.

## Table of Contents
- [Local Development Setup](#local-development-setup)
- [Production Deployment](#production-deployment)
- [Docker Deployment](#docker-deployment)
- [Cloud Deployment](#cloud-deployment)
- [Monitoring and Maintenance](#monitoring-and-maintenance)

## Local Development Setup

### Prerequisites
- Python 3.8 or higher
- MongoDB (local or cloud)
- AWS S3 bucket and credentials
- OpenAI API key (for CAPTCHA solving)
- Tesseract OCR (optional)

### Installation Steps

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd Playwright_WebScraping
   ```

2. **Create virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   playwright install firefox
   ```

4. **Install Tesseract OCR** (optional):
   - **macOS**: `brew install tesseract`
   - **Ubuntu**: `sudo apt-get install tesseract-ocr`
   - **Windows**: Download from [Tesseract GitHub](https://github.com/UB-Mannheim/tesseract/wiki)

5. **Configure environment**:
   ```bash
   cp .env.template .env
   # Edit .env with your configuration
   ```

### Environment Configuration

Edit the `.env` file with your settings:

```env
# MongoDB Configuration
MONGO_CONNECTION_STRING=mongodb://localhost:27017/
MONGO_DATABASE=supreme_court_judgments
MONGO_COLLECTION=judgments

# AWS S3 Configuration
AWS_ACCESS_KEY_ID=your_aws_access_key_here
AWS_SECRET_ACCESS_KEY=your_aws_secret_key_here
AWS_REGION=us-east-1
S3_BUCKET_NAME=your-s3-bucket-name
S3_FOLDER_PREFIX=judgments/

# OpenAI Configuration (for CAPTCHA solving)
OPENAI_API_KEY=your_openai_api_key_here
CAPTCHA_USE_OPENAI=true
OPENAI_MODEL=gpt-4o-mini

# Scraping Configuration
SCRAPING_START_YEAR=1995
SCRAPING_END_YEAR=2000
SCRAPING_HEADLESS=true

# Logging
LOG_LEVEL=INFO
LOG_FILE=scraper.log
```

### Running the Scraper

```bash
# Basic run
python main.py

# With custom date range
python main.py --start-year 2020 --end-year 2024

# Resume from previous session
python main.py --resume

# Show statistics
python main.py --stats

# Test CAPTCHA solving
python main.py --test-captcha

# Reset progress (use with caution)
python main.py --reset-progress
```

## Production Deployment

### System Requirements
- **CPU**: 2+ cores
- **RAM**: 4GB+ (8GB recommended)
- **Storage**: 50GB+ (depends on data volume)
- **Network**: Stable internet connection

### Production Setup

1. **Create production user**:
   ```bash
   sudo useradd -m -s /bin/bash scraper
   sudo su - scraper
   ```

2. **Install system dependencies**:
   ```bash
   # Ubuntu/Debian
   sudo apt update
   sudo apt install python3 python3-pip python3-venv git tesseract-ocr
   
   # CentOS/RHEL
   sudo yum install python3 python3-pip git tesseract
   ```

3. **Setup application**:
   ```bash
   git clone <repository-url> /opt/supreme-court-scraper
   cd /opt/supreme-court-scraper
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   playwright install firefox
   ```

4. **Configure environment**:
   ```bash
   cp .env.template .env
   # Edit .env with production settings
   chmod 600 .env  # Secure the environment file
   ```

5. **Create systemd service** (`/etc/systemd/system/supreme-court-scraper.service`):
   ```ini
   [Unit]
   Description=Supreme Court Judgment Scraper
   After=network.target
   
   [Service]
   Type=simple
   User=scraper
   WorkingDirectory=/opt/supreme-court-scraper
   Environment=PATH=/opt/supreme-court-scraper/venv/bin
   ExecStart=/opt/supreme-court-scraper/venv/bin/python main.py
   Restart=always
   RestartSec=10
   StandardOutput=journal
   StandardError=journal
   
   [Install]
   WantedBy=multi-user.target
   ```

6. **Start and enable service**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable supreme-court-scraper
   sudo systemctl start supreme-court-scraper
   ```

7. **Monitor service**:
   ```bash
   sudo systemctl status supreme-court-scraper
   sudo journalctl -u supreme-court-scraper -f
   ```

## Docker Deployment

### Dockerfile

Create a `Dockerfile`:

```dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install firefox
RUN playwright install-deps firefox

# Copy application code
COPY . .

# Create non-root user
RUN useradd -m -u 1000 scraper && chown -R scraper:scraper /app
USER scraper

# Run the application
CMD ["python", "main.py"]
```

### Docker Compose

Create a `docker-compose.yml`:

```yaml
version: '3.8'

services:
  scraper:
    build: .
    container_name: supreme-court-scraper
    restart: unless-stopped
    environment:
      - MONGO_CONNECTION_STRING=${MONGO_CONNECTION_STRING}
      - MONGO_DATABASE=${MONGO_DATABASE}
      - AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
      - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
      - AWS_REGION=${AWS_REGION}
      - S3_BUCKET_NAME=${S3_BUCKET_NAME}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - SCRAPING_START_YEAR=${SCRAPING_START_YEAR}
      - SCRAPING_END_YEAR=${SCRAPING_END_YEAR}
      - SCRAPING_HEADLESS=true
    volumes:
      - ./downloads:/app/downloads
      - ./logs:/app/logs
      - ./date_progress.json:/app/date_progress.json
    depends_on:
      - mongodb

  mongodb:
    image: mongo:6.0
    container_name: supreme-court-mongodb
    restart: unless-stopped
    environment:
      - MONGO_INITDB_ROOT_USERNAME=admin
      - MONGO_INITDB_ROOT_PASSWORD=password
    volumes:
      - mongodb_data:/data/db
    ports:
      - "27017:27017"

volumes:
  mongodb_data:
```

### Running with Docker

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f scraper

# Stop
docker-compose down

# Update and restart
docker-compose pull
docker-compose up -d --force-recreate
```

## Cloud Deployment

### AWS EC2 Deployment

1. **Launch EC2 instance**:
   - Instance type: t3.medium or larger
   - OS: Ubuntu 22.04 LTS
   - Security group: Allow SSH (22)

2. **Connect and setup**:
   ```bash
   ssh -i your-key.pem ubuntu@your-ec2-ip
   
   # Update system
   sudo apt update && sudo apt upgrade -y
   
   # Install Docker
   curl -fsSL https://get.docker.com -o get-docker.sh
   sh get-docker.sh
   sudo usermod -aG docker ubuntu
   
   # Install Docker Compose
   sudo curl -L "https://github.com/docker/compose/releases/download/v2.20.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
   sudo chmod +x /usr/local/bin/docker-compose
   
   # Clone and deploy
   git clone <repository-url>
   cd Playwright_WebScraping
   cp .env.template .env
   # Edit .env with your settings
   docker-compose up -d
   ```

### Google Cloud Platform

1. **Create VM instance**:
   ```bash
   gcloud compute instances create supreme-court-scraper \
     --image-family=ubuntu-2204-lts \
     --image-project=ubuntu-os-cloud \
     --machine-type=e2-medium \
     --zone=us-central1-a
   ```

2. **SSH and setup**:
   ```bash
   gcloud compute ssh supreme-court-scraper --zone=us-central1-a
   # Follow similar setup steps as AWS
   ```

### Azure VM

1. **Create VM**:
   ```bash
   az vm create \
     --resource-group myResourceGroup \
     --name supreme-court-scraper \
     --image UbuntuLTS \
     --admin-username azureuser \
     --generate-ssh-keys
   ```

2. **Connect and setup**:
   ```bash
   ssh azureuser@your-vm-ip
   # Follow similar setup steps
   ```

## Monitoring and Maintenance

### Log Management

1. **View logs**:
   ```bash
   # Systemd service logs
   sudo journalctl -u supreme-court-scraper -f
   
   # Application logs
   tail -f /opt/supreme-court-scraper/scraper.log
   
   # Docker logs
   docker-compose logs -f scraper
   ```

2. **Log rotation** (add to `/etc/logrotate.d/supreme-court-scraper`):
   ```
   /opt/supreme-court-scraper/*.log {
       daily
       missingok
       rotate 30
       compress
       delaycompress
       notifempty
       copytruncate
   }
   ```

### Health Monitoring

1. **Create health check script** (`health_check.py`):
   ```python
   #!/usr/bin/env python3
   import sys
   import subprocess
   import requests
   from datetime import datetime
   
   def check_service_status():
       try:
           result = subprocess.run(['systemctl', 'is-active', 'supreme-court-scraper'], 
                                 capture_output=True, text=True)
           return result.stdout.strip() == 'active'
       except:
           return False
   
   def check_mongodb_connection():
       # Add MongoDB connection check
       pass
   
   def check_s3_connection():
       # Add S3 connection check
       pass
   
   if __name__ == "__main__":
       if not check_service_status():
           print(f"[{datetime.now()}] Service is not running")
           sys.exit(1)
       print(f"[{datetime.now()}] All checks passed")
   ```

2. **Setup cron job**:
   ```bash
   # Add to crontab
   */5 * * * * /opt/supreme-court-scraper/health_check.py >> /var/log/health_check.log 2>&1
   ```

### Performance Monitoring

1. **Monitor system resources**:
   ```bash
   # CPU and memory usage
   htop
   
   # Disk usage
   df -h
   
   # Network usage
   iftop
   ```

2. **Monitor scraping progress**:
   ```bash
   # Check statistics
   python main.py --stats
   
   # Monitor progress file
   cat date_progress.json | jq .
   ```

### Backup and Recovery

1. **Backup configuration**:
   ```bash
   # Backup .env and progress files
   tar -czf backup-$(date +%Y%m%d).tar.gz .env date_progress.json
   ```

2. **Database backup**:
   ```bash
   # MongoDB backup
   mongodump --uri="$MONGO_CONNECTION_STRING" --out=backup-$(date +%Y%m%d)
   ```

3. **S3 backup verification**:
   ```bash
   # List S3 objects
   aws s3 ls s3://your-bucket-name/judgments/ --recursive
   ```

### Troubleshooting

#### Common Issues

1. **CAPTCHA solving failures**:
   - Check OpenAI API key and credits
   - Verify network connectivity
   - Test with `python main.py --test-captcha`

2. **MongoDB connection issues**:
   - Verify connection string
   - Check network connectivity
   - Ensure MongoDB is running

3. **S3 upload failures**:
   - Verify AWS credentials
   - Check bucket permissions
   - Ensure bucket exists

4. **Browser crashes**:
   - Increase system memory
   - Check for system updates
   - Restart the service

#### Debug Mode

```bash
# Run with debug logging
python main.py --log-level DEBUG

# Run without headless mode (local only)
python main.py --no-headless
```

## Security Considerations

1. **Environment variables**:
   - Never commit `.env` files to version control
   - Use proper file permissions (600)
   - Consider using secret management services

2. **Network security**:
   - Use VPC/private networks in cloud
   - Implement proper firewall rules
   - Use SSH key authentication

3. **Access control**:
   - Run with non-root user
   - Implement proper IAM policies for AWS
   - Regular security updates

4. **Data protection**:
   - Encrypt data at rest and in transit
   - Regular backups
   - Monitor access logs

## Scaling Considerations

1. **Horizontal scaling**:
   - Run multiple instances with different date ranges
   - Use load balancers for API endpoints
   - Implement distributed task queues

2. **Vertical scaling**:
   - Increase instance size for better performance
   - Optimize memory usage
   - Use SSD storage for better I/O

3. **Database scaling**:
   - Use MongoDB sharding for large datasets
   - Implement read replicas
   - Regular index optimization

This deployment guide provides comprehensive instructions for running the Supreme Court scraper in various environments. Choose the deployment method that best fits your infrastructure and requirements.