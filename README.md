# Playwright_WebScraping
Web Scraping, Automation, and CAPTCHA Solving with Playwright + Web Unlocker

## Introduction

This repository stores code that was featured in my <a href="https://youtu.be/RGR5Xj0Qqfs" target="_blank">Playwright Youtube tutorial</a>.
<br>
<br>
<img src="https://github.com/user-attachments/assets/8ce05e61-6050-4c82-8c1e-f45e16c88919" width=600px>

## Recommended Environment Setup

```
>> conda create -n env_name python=3.11
>> conda activate env_name
>> pip install pytest-playwright
>> playwright install
>> playwright install-deps
```

## Files
- **quickstart.py** includes a basic Playwright syntax of navigating to a web page and fetching its source code, title and screenshot.
- **PDF_scraper.py** web scrapes keyword-based research papers from Arxiv.org and automatically downloads them to a local machine.
- **CAPTCHA_solver.py** includes a basic implementation of a CAPTCHA solving mechanism named Web Unlocker, by Bright Data.




