#!/bin/bash

# Supreme Court Scraper Deployment Script
# This script automates the deployment process

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to detect OS
detect_os() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if command_exists apt-get; then
            echo "ubuntu"
        elif command_exists yum; then
            echo "centos"
        else
            echo "linux"
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        echo "macos"
    else
        echo "unknown"
    fi
}

# Function to install system dependencies
install_system_deps() {
    local os=$(detect_os)
    print_status "Installing system dependencies for $os..."
    
    case $os in
        "ubuntu")
            sudo apt update
            sudo apt install -y python3 python3-pip python3-venv git tesseract-ocr curl
            ;;
        "centos")
            sudo yum update -y
            sudo yum install -y python3 python3-pip git tesseract curl
            ;;
        "macos")
            if command_exists brew; then
                brew install python3 tesseract
            else
                print_warning "Homebrew not found. Please install Python 3 and Tesseract manually."
            fi
            ;;
        *)
            print_warning "Unknown OS. Please install Python 3, pip, git, and tesseract manually."
            ;;
    esac
}

# Function to setup Python environment
setup_python_env() {
    print_status "Setting up Python virtual environment..."
    
    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi
    
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    
    print_status "Installing Playwright browsers..."
    playwright install firefox
    
    # Install system dependencies for Playwright
    if [[ $(detect_os) == "ubuntu" ]]; then
        playwright install-deps firefox
    fi
}

# Function to setup configuration
setup_config() {
    print_status "Setting up configuration..."
    
    if [ ! -f ".env" ]; then
        if [ -f ".env.template" ]; then
            cp .env.template .env
            print_warning "Configuration file created from template. Please edit .env with your settings."
        else
            print_error ".env.template not found. Please create .env manually."
            return 1
        fi
    else
        print_success "Configuration file already exists."
    fi
    
    # Set secure permissions
    chmod 600 .env
}

# Function to create systemd service
create_systemd_service() {
    local install_dir=$(pwd)
    local service_file="/etc/systemd/system/supreme-court-scraper.service"
    
    print_status "Creating systemd service..."
    
    sudo tee $service_file > /dev/null <<EOF
[Unit]
Description=Supreme Court Judgment Scraper
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$install_dir
Environment=PATH=$install_dir/venv/bin
ExecStart=$install_dir/venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable supreme-court-scraper
    
    print_success "Systemd service created and enabled."
}

# Function to create Docker setup
setup_docker() {
    print_status "Setting up Docker configuration..."
    
    # Create Dockerfile if it doesn't exist
    if [ ! -f "Dockerfile" ]; then
        cat > Dockerfile <<EOF
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \\
    wget \\
    gnupg \\
    tesseract-ocr \\
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
EOF
        print_success "Dockerfile created."
    fi
    
    # Create docker-compose.yml if it doesn't exist
    if [ ! -f "docker-compose.yml" ]; then
        cat > docker-compose.yml <<EOF
version: '3.8'

services:
  scraper:
    build: .
    container_name: supreme-court-scraper
    restart: unless-stopped
    env_file:
      - .env
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
EOF
        print_success "docker-compose.yml created."
    fi
}

# Function to validate configuration
validate_config() {
    print_status "Validating configuration..."
    
    if [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
        python -c "from config import config; config.validate()" 2>/dev/null
        if [ $? -eq 0 ]; then
            print_success "Configuration validation passed."
        else
            print_warning "Configuration validation failed. Please check your .env file."
        fi
    else
        print_warning "Virtual environment not found. Skipping validation."
    fi
}

# Function to show usage
show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --local         Setup for local development"
    echo "  --production    Setup for production deployment"
    echo "  --docker        Setup Docker configuration"
    echo "  --systemd       Create systemd service (requires sudo)"
    echo "  --validate      Validate configuration only"
    echo "  --help          Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 --local                 # Setup for local development"
    echo "  $0 --production --systemd   # Setup for production with systemd"
    echo "  $0 --docker                # Setup Docker configuration"
}

# Main deployment function
main() {
    local setup_type=""
    local create_service=false
    local docker_setup=false
    local validate_only=false
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --local)
                setup_type="local"
                shift
                ;;
            --production)
                setup_type="production"
                shift
                ;;
            --docker)
                docker_setup=true
                shift
                ;;
            --systemd)
                create_service=true
                shift
                ;;
            --validate)
                validate_only=true
                shift
                ;;
            --help)
                show_usage
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                show_usage
                exit 1
                ;;
        esac
    done
    
    # If no arguments provided, show usage
    if [[ -z "$setup_type" && "$docker_setup" == false && "$validate_only" == false ]]; then
        show_usage
        exit 1
    fi
    
    print_status "Starting Supreme Court Scraper deployment..."
    
    # Validate only mode
    if [[ "$validate_only" == true ]]; then
        validate_config
        exit 0
    fi
    
    # Docker setup
    if [[ "$docker_setup" == true ]]; then
        setup_docker
        print_success "Docker setup completed. Run 'docker-compose up -d' to start."
        exit 0
    fi
    
    # Check if we're in the right directory
    if [ ! -f "main.py" ] || [ ! -f "requirements.txt" ]; then
        print_error "This doesn't appear to be the Supreme Court Scraper directory."
        print_error "Please run this script from the project root directory."
        exit 1
    fi
    
    # Install system dependencies for production
    if [[ "$setup_type" == "production" ]]; then
        install_system_deps
    fi
    
    # Setup Python environment
    setup_python_env
    
    # Setup configuration
    setup_config
    
    # Create systemd service if requested
    if [[ "$create_service" == true ]]; then
        if [[ "$EUID" -eq 0 ]]; then
            print_error "Please don't run this script as root when creating systemd service."
            print_error "The script will use sudo when needed."
            exit 1
        fi
        create_systemd_service
    fi
    
    # Validate configuration
    validate_config
    
    print_success "Deployment completed successfully!"
    
    # Show next steps
    echo ""
    print_status "Next steps:"
    echo "1. Edit .env file with your configuration"
    echo "2. Test the setup: python main.py --test-captcha"
    
    if [[ "$create_service" == true ]]; then
        echo "3. Start the service: sudo systemctl start supreme-court-scraper"
        echo "4. Check status: sudo systemctl status supreme-court-scraper"
        echo "5. View logs: sudo journalctl -u supreme-court-scraper -f"
    else
        echo "3. Run the scraper: python main.py"
    fi
    
    echo ""
    print_status "For more information, see DEPLOYMENT_GUIDE.md"
}

# Run main function with all arguments
main "$@"