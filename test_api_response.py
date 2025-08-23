#!/usr/bin/env python3
"""
Test script to analyze the actual API response structure
from the Supreme Court website and fix table detection issues.
"""

import json
from bs4 import BeautifulSoup
from supreme_court_scraper import SupremeCourtScraper
from config import config
from loguru import logger

# Sample API response data from the user's screenshot
sample_api_response = {
    "success": True,
    "data": {
        "pagination": False,
        "resultsHtml": '''<div class="text-center mr-top15">
            <a href="https://www.sci.gov.in/" title="Go to home" class="site_logo" rel="home">
                <img class="emblem state-emb" id="logo" src="https://cdnbbsr.s3waas.gov.in/s3ec0490f1f4972d133619a60c30f3559e/uploads/2023/05/2023051729.png">
            </a>
            <br/>
            <p class="mr-top15"><strong>SUPREME COURT OF INDIA</strong><br/>
            </p>
        </div>
        <div class="distTableContent">
            <table class="">
                <thead>
                    <tr>
                        <th scope="col">Serial Number</th>
                        <th scope="col">Diary Number</th>
                        <th scope="col">Case Number</th>
                        <th scope="col">Petitioner / Respondent</th>
                        <th scope="col">Petitioner/Respondent Advocate</th>
                        <th scope="col">Bench</th>
                        <th scope="col">Judgment Date</th>
                        <th scope="col">Judgment</th>
                    </tr>
                </thead>
                <tbody>
                    <tr id="732996803216c6ca3c16e9142b5125" data-diary-no="/9948">
                        <td>1</td>
                        <td>/9948</td>
                        <td>-</td>
                        <td class="petitioners text-center">
                            <div></div>
                        </td>
                        <td>
                            <p class="respondents"><div><br> <center> _ </center> <br></div></p>
                            <td>1</td><br>R.C. LAHOTI<br>B.N. AGRAWAL<br>DR. AR. LAKSHMANAN.</td>
                        </td>
                        <td>
                            <a target="_blank" href="https://api.sci.gov.in/jonew/judis/25825.pdf">15-01-2004(English) <br></a><br/><a target="_blank">
                        </td>
                    </tr>
                    <tr id="d01ea78633dd4a76025a68831f616b" data-diary-no="12/2004">
                        <td>2</td>
                        <td>12/2004</td>
                        <td>C.A. No.-000131-000131 - 2004</td>
                        <td class="petitioners text-center">
                            <div></div>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>'''
    }
}

def test_api_response_parsing():
    """Test parsing of the actual API response structure"""
    print("=== Testing API Response Parsing ===")
    
    # Initialize scraper
    scraper = SupremeCourtScraper(config)
    
    # Test JSON parsing
    print("\n1. Testing JSON structure:")
    print(f"Success: {sample_api_response['success']}")
    print(f"Pagination: {sample_api_response['data']['pagination']}")
    print(f"HTML length: {len(sample_api_response['data']['resultsHtml'])} characters")
    
    # Test HTML parsing
    print("\n2. Testing HTML parsing:")
    html_content = sample_api_response['data']['resultsHtml']
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Find tables
    tables = soup.find_all('table')
    print(f"Found {len(tables)} table(s)")
    
    if tables:
        table = tables[0]
        rows = table.find_all('tr')
        print(f"Table has {len(rows)} rows")
        
        # Analyze each row
        for i, row in enumerate(rows):
            cells = row.find_all(['td', 'th'])
            print(f"Row {i+1}: {len(cells)} cells")
            if i == 0:  # Header row
                headers = [cell.get_text().strip() for cell in cells]
                print(f"Headers: {headers}")
            elif i <= 2:  # First few data rows
                cell_data = [cell.get_text().strip()[:50] + '...' if len(cell.get_text().strip()) > 50 else cell.get_text().strip() for cell in cells]
                print(f"Row {i+1} data: {cell_data}")
    
    # Test with scraper's parsing method
    print("\n3. Testing with scraper's _parse_table_from_soup method:")
    judgments = scraper._parse_table_from_soup(soup)
    print(f"Extracted {len(judgments)} judgments")
    
    for i, judgment in enumerate(judgments):
        print(f"\nJudgment {i+1}:")
        for key, value in judgment.items():
            print(f"  {key}: {value}")
    
    # Test network response processing
    print("\n4. Testing network response processing:")
    mock_responses = [{
        'url': 'https://www.sci.gov.in/wp-admin/admin-ajax.php?action=get_judgements_judgement_date',
        'body': json.dumps(sample_api_response),
        'status': 200
    }]
    
    # Temporarily set captured responses
    scraper.captured_responses = mock_responses
    extracted_judgments = scraper._extract_from_network_responses()
    print(f"Network extraction found {len(extracted_judgments)} judgments")
    
    for i, judgment in enumerate(extracted_judgments):
        print(f"\nNetwork Judgment {i+1}:")
        for key, value in judgment.items():
            print(f"  {key}: {value}")
    
    return len(judgments) > 0 and len(extracted_judgments) > 0

def explain_google_analytics_approach():
    """Explain why Google Analytics was considered"""
    print("\n=== Google Analytics Approach Explanation ===")
    print("""
    The Google Analytics approach was implemented as a fallback strategy because:
    
    1. **Primary Issue**: The main API endpoint sometimes returns data that doesn't 
       get properly rendered in the DOM, causing timeouts when waiting for #cnrresults.
    
    2. **Google Analytics Tracking**: Some websites embed judgment data in GA tracking 
       calls for analytics purposes, especially for user engagement tracking.
    
    3. **Fallback Strategy**: If the main API parsing fails, we check GA calls as 
       an alternative data source.
    
    However, based on your screenshot, the MAIN API endpoint is working correctly:
    - URL: /wp-admin/admin-ajax.php?action=get_judgements_judgement_date
    - Returns JSON with 'data.resultsHtml' containing the table
    - This should be our PRIMARY parsing target
    
    The issue is likely in how we're processing the JSON response structure.
    """)

def main():
    """Main test function"""
    logger.info("Starting API response analysis...")
    
    # Test API response parsing
    success = test_api_response_parsing()
    
    # Explain GA approach
    explain_google_analytics_approach()
    
    print("\n=== Summary ===")
    if success:
        print("✅ API response parsing is working correctly")
        print("✅ The main issue is likely in JSON structure handling")
        print("✅ Focus should be on the admin-ajax.php endpoint, not Google Analytics")
    else:
        print("❌ API response parsing needs fixes")
    
    print("\n=== Recommendations ===")
    print("1. Comment out S3 upload code as requested")
    print("2. Focus on admin-ajax.php JSON response parsing")
    print("3. Improve table detection in 'data.resultsHtml'")
    print("4. Save extracted data directly to MongoDB")

if __name__ == "__main__":
    main()