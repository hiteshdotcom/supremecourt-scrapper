⏺ Here's the complete step-by-step guide to run it continuously on an EC2 server using systemd (the most reliable
  approach):

  ---
  Step 1 — SSH into your EC2 server

  ssh -i your-key.pem ubuntu@your-ec2-ip

  ---
  Step 2 — Install dependencies

  sudo apt update && sudo apt install -y python3 python3-pip python3-venv git tesseract-ocr

  ---
  Step 3 — Upload/clone the project

  # Option A: copy from local machine
  scp -i your-key.pem -r /Users/hiteshpal/Desktop/ai-lawyer-mvp/Playwright_WebScraping ubuntu@your-ec2-ip:/opt/scraper

  # Option B: git clone (if on GitHub)
  git clone <your-repo-url> /opt/scraper

  ---
  Step 4 — Set up Python environment

  cd /opt/scraper
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt
  playwright install firefox
  playwright install-deps firefox

  ---
  Step 5 — Configure .env

  cp .env.template .env
  nano .env          # fill in MongoDB, AWS, OpenAI keys
  chmod 600 .env     # secure the file

  ---
  Step 6 — Create the systemd service

  sudo nano /etc/systemd/system/supreme-court-scraper.service

  Paste this (replace /opt/scraper with your actual path and ubuntu with your user):

  [Unit]
  Description=Supreme Court Judgment Scraper
  After=network.target

  [Service]
  Type=simple
  User=ubuntu
  WorkingDirectory=/opt/scraper
  Environment=PATH=/opt/scraper/venv/bin
  ExecStart=/opt/scraper/venv/bin/python main.py
  Restart=always
  RestartSec=30
  StandardOutput=journal
  StandardError=journal

  [Install]
  WantedBy=multi-user.target

  ---
  Step 7 — Start and enable it

  sudo systemctl daemon-reload
  sudo systemctl enable supreme-court-scraper   # auto-start on reboot
  sudo systemctl start supreme-court-scraper

  ---
  Step 8 — Monitor it

  # Check status
  sudo systemctl status supreme-court-scraper

  # Watch live logs
  sudo journalctl -u supreme-court-scraper -f

  # Check scraper's own log file
  tail -f /opt/scraper/supreme_court_scraper.log

  ---
  Useful commands

  ┌────────────────────┬───────────────────────────────────────────────────────────────────────┐
  │       Action       │                                Command                                │
  ├────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ Stop               │ sudo systemctl stop supreme-court-scraper                             │
  ├────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ Restart            │ sudo systemctl restart supreme-court-scraper                          │
  ├────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ Disable auto-start │ sudo systemctl disable supreme-court-scraper                          │
  ├────────────────────┼───────────────────────────────────────────────────────────────────────┤
  │ Check progress     │ cd /opt/scraper && source venv/bin/activate && python main.py --stats │
  └────────────────────┴───────────────────────────────────────────────────────────────────────┘

  ---
  Restart=always with RestartSec=30 means if the script crashes (network error, CAPTCHA failure, etc.) it will
  automatically restart after 30 seconds and continue from where it left off (via date_progress.json).
