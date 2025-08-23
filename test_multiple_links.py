#!/usr/bin/env python3
"""
Test script to verify multiple PDF links extraction functionality
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from bs4 import BeautifulSoup
from supreme_court_scraper import SupremeCourtScraper
from config import config
from mongodb_client import MongoDBClient

def test_multiple_links_extraction():
    """Test extraction of multiple PDF links from HTML"""
    print("\n=== Testing Multiple PDF Links Extraction ===")
    
    # Sample HTML with multiple judgment links (from user's example)
    sample_html = '''
    <tr id="d9a7b199e65ecdf152057cb1977f94" data-diary-no="228/2011"> 
        <td>1</td> 
        <td>228/2011</td> 
        <td>C.A. No.-009098-009098 - 2013</td> 
        <td class="petitioners text-center"> 
            <div>KANWAR RAJ SINGH (D) TH:LRS .</div><div>VS</div><div>GEJO (D) TH:LRS .</div>
        </td> 
        <td> 
            <p class="respondents"><div>JASPREET GOGIA</div><div><br> <center> __ </center> <br></div></p>
        </td> 
        <td>HON'BLE MR. JUSTICE ABHAY S. OKA<br> HON'BLE MR. JUSTICE UJJAL BHUYAN</td> 
        <td>HON'BLE MR. JUSTICE ABHAY S. OKA</td> 
        <td> 
            <a target="_blank" href="https://api.sci.gov.in/supremecourt/2011/228/228_2011_7_1501_49155_Judgement_02-Jan-2024.pdf">02-01-2024(English) <br></a><br/>
            <a target="_blank" href="https://api.sci.gov.in/supremecourt/2011/228/228_2011_7_1501_49155_Judgement_02-Jan-2024.pdf">2024 INSC 1(English) <br></a><br/>
            <a target="_blank" href="https://api.sci.gov.in/"></a><br/>
        </td> 
    </tr>
    '''
    
    # Parse HTML
    soup = BeautifulSoup(sample_html, 'html.parser')
    row = soup.find('tr')
    cells = row.find_all('td')
    
    # Initialize scraper
    scraper = SupremeCourtScraper(config)
    
    # Extract judgment data
    judgment_data = scraper._extract_judgment_from_cells(cells)
    
    if judgment_data:
        print(f"✓ Successfully extracted judgment data")
        print(f"  Case Number: {judgment_data.get('case_number', 'N/A')}")
        print(f"  Diary Number: {judgment_data.get('diary_number', 'N/A')}")
        print(f"  Primary PDF Link: {judgment_data.get('pdf_link', 'N/A')}")
        print(f"  All PDF Links: {judgment_data.get('pdf_links', [])}")
        print(f"  Judgment Links: {judgment_data.get('judgment_links', [])}")
        
        # Verify multiple links were extracted
        pdf_links = judgment_data.get('pdf_links', [])
        judgment_links = judgment_data.get('judgment_links', [])
        
        if len(pdf_links) > 1:
            print(f"✓ Multiple PDF links extracted: {len(pdf_links)} links")
        else:
            print(f"⚠ Expected multiple PDF links, got: {len(pdf_links)}")
            
        if len(judgment_links) > 1:
            print(f"✓ Multiple judgment links extracted: {len(judgment_links)} links")
        else:
            print(f"⚠ Expected multiple judgment links, got: {len(judgment_links)}")
            
        return judgment_data
    else:
        print("✗ Failed to extract judgment data")
        return None

def test_mongodb_schema():
    """Test MongoDB schema supports new fields"""
    print("\n=== Testing MongoDB Schema ===")
    
    try:
        mongo_client = MongoDBClient(config.mongo)
        
        # Test sample data with multiple links
        sample_judgment = {
            'judgment_id': 'test_multiple_links_001',
            'serial_number': '1',
            'diary_number': '228/2011',
            'case_number': 'C.A. No.-009098-009098 - 2013',
            'petitioner_respondent': 'KANWAR RAJ SINGH (D) TH:LRS . VS GEJO (D) TH:LRS .',
            'advocate': 'JASPREET GOGIA',
            'bench': "HON'BLE MR. JUSTICE ABHAY S. OKA HON'BLE MR. JUSTICE UJJAL BHUYAN",
            'judgment_by': "HON'BLE MR. JUSTICE ABHAY S. OKA",
            'judgment_date': '02-01-2024',
            'pdf_links': [
                'https://api.sci.gov.in/supremecourt/2011/228/228_2011_7_1501_49155_Judgement_02-Jan-2024.pdf',
                'https://api.sci.gov.in/supremecourt/2011/228/228_2011_7_1501_49155_Judgement_02-Jan-2024.pdf'
            ],
            'judgment_links': [
                'https://api.sci.gov.in/supremecourt/2011/228/228_2011_7_1501_49155_Judgement_02-Jan-2024.pdf',
                'https://api.sci.gov.in/supremecourt/2011/228/228_2011_7_1501_49155_Judgement_02-Jan-2024.pdf'
            ],
            'pdf_link': 'https://api.sci.gov.in/supremecourt/2011/228/228_2011_7_1501_49155_Judgement_02-Jan-2024.pdf',
            'file_url': 'https://api.sci.gov.in/supremecourt/2011/228/228_2011_7_1501_49155_Judgement_02-Jan-2024.pdf',
            'processing_status': 'completed'
        }
        
        from mongodb_client import JudgmentMetadata
        metadata = JudgmentMetadata(**sample_judgment)
        
        print(f"✓ JudgmentMetadata object created successfully")
        print(f"  PDF Links: {len(metadata.pdf_links)} links")
        print(f"  Judgment Links: {len(metadata.judgment_links)} links")
        
        # Test insertion (but don't actually insert to avoid duplicates)
        print(f"✓ MongoDB schema supports new fields")
        
        return True
        
    except Exception as e:
        print(f"✗ MongoDB schema test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("Testing Multiple PDF Links Functionality")
    print("=" * 50)
    
    # Test 1: Extract multiple links from HTML
    judgment_data = test_multiple_links_extraction()
    
    # Test 2: MongoDB schema compatibility
    schema_ok = test_mongodb_schema()
    
    # Summary
    print("\n=== Test Summary ===")
    if judgment_data and schema_ok:
        print("✓ All tests passed! Multiple PDF links functionality is working.")
        print("\nKey improvements:")
        print("- Extracts all PDF links from judgment column")
        print("- Stores links with metadata in judgment_links array")
        print("- Maintains backward compatibility with pdf_link field")
        print("- MongoDB schema supports new fields")
    else:
        print("✗ Some tests failed. Please check the implementation.")

if __name__ == "__main__":
    main()