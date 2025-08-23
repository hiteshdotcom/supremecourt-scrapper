#!/usr/bin/env python3
"""
Test script to verify API response parsing functionality
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from supreme_court_scraper import SupremeCourtScraper
from config import config
from bs4 import BeautifulSoup
import json
from loguru import logger

def test_html_parsing():
    """Test HTML table parsing with sample data"""
    
    # Sample HTML table structure similar to what we might get from the API
    sample_html = """
    <table>
        <thead>
            <tr>
                <th>S.No.</th>
                <th>Diary No.</th>
                <th>Case No.</th>
                <th>Petitioner/Respondent</th>
                <th>Advocate</th>
                <th>Date</th>
                <th>Download</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>1</td>
                <td>12345</td>
                <td>SLP(C) No. 1234/2024</td>
                <td>ABC vs XYZ</td>
                <td>Mr. John Doe</td>
                <td>15-01-2024</td>
                <td><a href="/judgment/12345.pdf">Download PDF</a></td>
            </tr>
            <tr>
                <td>2</td>
                <td>12346</td>
                <td>Civil Appeal No. 5678/2024</td>
                <td>DEF vs GHI</td>
                <td>Ms. Jane Smith</td>
                <td>16-01-2024</td>
                <td><a href="javascript:void(0)" onclick="window.open('/download/judgment/12346.pdf')">View</a></td>
            </tr>
        </tbody>
    </table>
    """
    
    # Create scraper instance
    scraper = SupremeCourtScraper(config)
    
    # Parse the HTML
    soup = BeautifulSoup(sample_html, 'html.parser')
    judgments = scraper._parse_table_from_soup(soup)
    
    print(f"\n=== HTML Parsing Test ===")
    print(f"Found {len(judgments)} judgments:")
    for i, judgment in enumerate(judgments, 1):
        print(f"\nJudgment {i}:")
        for key, value in judgment.items():
            print(f"  {key}: {value}")
    
    return len(judgments) > 0

def test_network_response_simulation():
    """Test network response parsing with simulated data"""
    
    # Create scraper instance
    scraper = SupremeCourtScraper(config)
    
    # Simulate captured network responses
    sample_html_response = """
    <div id="results">
        <table class="judgment-table">
            <tr>
                <td>1</td>
                <td>D12345</td>
                <td>SLP(C) No. 9999/2024</td>
                <td>Test Case vs Another Case</td>
                <td>Advocate Name</td>
                <td>20-01-2024</td>
                <td><a href="/judgments/test.pdf">Download</a></td>
            </tr>
        </table>
    </div>
    """
    
    # Simulate the captured_responses structure
    scraper.captured_responses = [
        {
            'url': 'https://www.sci.gov.in/wp-admin/admin-ajax.php?action=get_judgements_judgement_date',
            'body': sample_html_response,
            'status': 200
        }
    ]
    
    # Debug: Print the HTML structure
    print(f"\nDEBUG: Sample HTML response:")
    print(sample_html_response)
    
    # Debug: Parse and check table structure
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(sample_html_response, 'html.parser')
    table = soup.find('table')
    if table:
        rows = table.find_all('tr')
        print(f"\nDEBUG: Found table with {len(rows)} rows")
        for i, row in enumerate(rows):
            cells = row.find_all('td')
            print(f"  Row {i+1}: {len(cells)} cells")
            if cells:
                for j, cell in enumerate(cells):
                    print(f"    Cell {j+1}: '{cell.get_text(strip=True)}'")
    else:
        print("\nDEBUG: No table found in HTML")
    
    # Test extraction
    judgments = scraper._extract_from_network_responses()
    
    print(f"\n=== Network Response Parsing Test ===")
    print(f"Found {len(judgments)} judgments from network responses:")
    for i, judgment in enumerate(judgments, 1):
        print(f"\nJudgment {i}:")
        for key, value in judgment.items():
            print(f"  {key}: {value}")
    
    return len(judgments) > 0

def main():
    """Run all tests"""
    print("Testing API Response Parsing Functionality")
    print("=" * 50)
    
    # Test HTML parsing
    html_test_passed = test_html_parsing()
    
    # Test network response simulation
    network_test_passed = test_network_response_simulation()
    
    print(f"\n=== Test Results ===")
    print(f"HTML Parsing Test: {'PASSED' if html_test_passed else 'FAILED'}")
    print(f"Network Response Test: {'PASSED' if network_test_passed else 'FAILED'}")
    
    if html_test_passed and network_test_passed:
        print("\n✅ All tests passed! API response parsing is working correctly.")
        return True
    else:
        print("\n❌ Some tests failed. Check the implementation.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)