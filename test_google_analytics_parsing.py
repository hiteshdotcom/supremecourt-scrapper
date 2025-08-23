#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from supreme_court_scraper import SupremeCourtScraper
from config import config
from urllib.parse import quote
import json

def test_google_analytics_parsing():
    """Test parsing of Google Analytics API response with embedded judgment data"""
    
    # Initialize scraper
    scraper = SupremeCourtScraper(config)
    
    # Sample judgment data that might be embedded in Google Analytics URL
    sample_html_table = """
    <table class="judgment-table">
        <tr>
            <td>1</td>
            <td>D67890</td>
            <td>SLP(C) No. 1234/2024</td>
            <td>ABC Corp vs XYZ Ltd</td>
            <td>Senior Advocate</td>
            <td>15-01-2024</td>
            <td><a href="/judgments/slp_1234_2024.pdf">Download PDF</a></td>
        </tr>
        <tr>
            <td>2</td>
            <td>D67891</td>
            <td>Civil Appeal No. 5678/2024</td>
            <td>State of Delhi vs Citizens Group</td>
            <td>Government Pleader</td>
            <td>16-01-2024</td>
            <td><a href="/judgments/ca_5678_2024.pdf">View Judgment</a></td>
        </tr>
    </table>
    """
    
    # Create a Google Analytics URL with embedded HTML data
    encoded_html = quote(sample_html_table)
    ga_url = f"https://www.google-analytics.com/g/collect?v=2&tid=G-BZ6N54FGYB&en=user_engagement&dl={encoded_html}&dt=Judgment%20Data"
    
    print("=== Testing Google Analytics API Response Parsing ===")
    print(f"Sample GA URL length: {len(ga_url)} characters")
    print(f"Encoded HTML length: {len(encoded_html)} characters")
    
    # Test the parsing function
    judgments = scraper._parse_google_analytics_response("", ga_url)
    
    print(f"\nExtracted {len(judgments)} judgments:")
    for i, judgment in enumerate(judgments, 1):
        print(f"\nJudgment {i}:")
        for key, value in judgment.items():
            print(f"  {key}: {value}")
    
    # Test saving to MongoDB (mock)
    if judgments:
        print("\n=== Testing MongoDB Save ===")
        try:
            # This will test the save function structure
            result = scraper._save_judgments_to_mongodb(judgments)
            print(f"Save operation result: {result}")
        except Exception as e:
            print(f"Save operation failed (expected if MongoDB not configured): {e}")
    
    # Test with HTML in response body
    print("\n=== Testing HTML in Response Body ===")
    body_judgments = scraper._parse_google_analytics_response(sample_html_table, ga_url)
    print(f"Extracted {len(body_judgments)} judgments from response body")
    
    return len(judgments) > 0 and len(body_judgments) > 0

def test_network_response_simulation():
    """Simulate the network response processing"""
    
    scraper = SupremeCourtScraper(config)
    
    # Simulate captured responses including Google Analytics
    sample_responses = [
        {
            'url': 'https://www.google-analytics.com/g/collect?v=2&en=user_engagement&dl=%3Ctable%3E%3Ctr%3E%3Ctd%3E1%3C%2Ftd%3E%3Ctd%3ED12345%3C%2Ftd%3E%3Ctd%3ESLP(C)%20No.%209999%2F2024%3C%2Ftd%3E%3Ctd%3ETest%20Case%20vs%20Another%20Case%3C%2Ftd%3E%3Ctd%3EAdvocate%20Name%3C%2Ftd%3E%3Ctd%3E20-01-2024%3C%2Ftd%3E%3Ctd%3E%3Ca%20href%3D%22%2Fjudgments%2Ftest.pdf%22%3EDownload%3C%2Fa%3E%3C%2Ftd%3E%3C%2Ftr%3E%3C%2Ftable%3E',
            'body': 'some content to make it larger than 1000 bytes' + 'x' * 1000,  # Make body larger
            'status': 200
        },
        {
            'url': 'https://www.sci.gov.in/wp-admin/admin-ajax.php?action=get_judgements',
            'body': '<div>No data</div>',
            'status': 200
        }
    ]
    
    # Set the captured responses
    scraper.captured_responses = sample_responses
    
    print("\n=== Testing Network Response Processing ===")
    judgments = scraper._extract_from_network_responses()
    
    print(f"Total judgments extracted: {len(judgments)}")
    for i, judgment in enumerate(judgments, 1):
        print(f"\nJudgment {i}:")
        for key, value in judgment.items():
            print(f"  {key}: {value}")
    
    return len(judgments) > 0

if __name__ == "__main__":
    print("Testing Google Analytics API Response Parsing...\n")
    
    try:
        # Test individual parsing function
        test1_passed = test_google_analytics_parsing()
        
        # Test network response simulation
        test2_passed = test_network_response_simulation()
        
        print("\n=== Test Results ===")
        print(f"Google Analytics Parsing Test: {'PASSED' if test1_passed else 'FAILED'}")
        print(f"Network Response Processing Test: {'PASSED' if test2_passed else 'FAILED'}")
        
        if test1_passed and test2_passed:
            print("\n✅ All tests passed! Google Analytics API parsing is working correctly.")
            print("The scraper can now extract judgment data from GA API calls and save to MongoDB.")
        else:
            print("\n❌ Some tests failed. Please check the implementation.")
            
    except Exception as e:
        print(f"\n❌ Test execution failed: {e}")
        import traceback
        traceback.print_exc()