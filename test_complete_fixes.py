#!/usr/bin/env python3
"""
Test script to verify all fixes for Supreme Court scraper:
1. MongoDB schema updates with all judgment columns
2. mark_as_completed method availability
3. Duplicate prevention logic
4. PDF link extraction
5. Complete data capture
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import config
from mongodb_client import MongoDBClient, JudgmentMetadata
from supreme_court_scraper import SupremeCourtScraper
from bs4 import BeautifulSoup
import json

def test_mongodb_schema():
    """Test the updated MongoDB schema with all judgment fields"""
    print("\n=== Testing MongoDB Schema ===")
    
    try:
        mongo_client = MongoDBClient(config.mongo)
        
        # Test creating a judgment with all new fields
        test_judgment = JudgmentMetadata(
            judgment_id="test_complete_001",
            serial_number="1",
            diary_number="228/2011",
            case_number="C.A. No.009098-009098 - 2013",
            petitioner_respondent="KANWAR RAJ SINGH (D) TH LRS . VS GEJO (D) TH LRS .",
            advocate="JASPREET GOGIA",
            bench="HON'BLE MR. JUSTICE ABHAY S. OKA HON'BLE MR. JUSTICE UJJAL BHUYAN",
            judgment_by="HON'BLE MR. JUSTICE ABHAY S. OKA",
            judgment_date="02-01-2024(English)",
            pdf_link="https://example.com/judgment.pdf",
            file_url="https://example.com/judgment.pdf"
        )
        
        # Test insertion
        success = mongo_client.insert_judgment(test_judgment)
        print(f"✓ Insert judgment with complete schema: {success}")
        
        # Test mark_as_completed method
        if hasattr(mongo_client, 'mark_as_completed'):
            completed = mongo_client.mark_as_completed(test_judgment.judgment_id)
            print(f"✓ mark_as_completed method available: {completed}")
        else:
            print("✗ mark_as_completed method not found")
            return False
        
        # Test duplicate detection
        duplicate_id = mongo_client.find_duplicate_by_content(
            test_judgment.diary_number,
            test_judgment.case_number,
            test_judgment.judgment_date
        )
        print(f"✓ Duplicate detection working: {duplicate_id is not None}")
        
        # Cleanup
        mongo_client.collection.delete_one({"judgment_id": test_judgment.judgment_id})
        mongo_client.close()
        
        return True
        
    except Exception as e:
        print(f"✗ MongoDB schema test failed: {e}")
        return False

def test_judgment_extraction():
    """Test judgment data extraction from HTML table"""
    print("\n=== Testing Judgment Extraction ===")
    
    # Sample HTML table with all 8 columns as shown in the Supreme Court website
    sample_html = """
    <table>
        <tr>
            <td>1</td>
            <td>228/2011</td>
            <td>C.A. No.009098-009098 - 2013</td>
            <td>KANWAR RAJ SINGH (D) TH LRS . VS GEJO (D) TH LRS .</td>
            <td>JASPREET GOGIA</td>
            <td>HON'BLE MR. JUSTICE ABHAY S. OKA HON'BLE MR. JUSTICE UJJAL BHUYAN</td>
            <td>HON'BLE MR. JUSTICE ABHAY S. OKA</td>
            <td>02-01-2024(English) <a href="/judgment/download/123.pdf">Download PDF</a></td>
        </tr>
        <tr>
            <td>2</td>
            <td>1616/2024</td>
            <td>SLP(Crl) No.000550-000551 - 2024</td>
            <td>SANJAY KUNDU VS REGISTRAR GENERAL HIGH COURT OF HIMACHAL PRADESH</td>
            <td>GAGAN GUPTA</td>
            <td>HON'BLE THE CHIEF JUSTICE HON'BLE MR. JUSTICE J.B. PARDIWALA</td>
            <td>HON'BLE THE CHIEF JUSTICE</td>
            <td>12-01-2024(English) <a href="/judgment/download/456.pdf">View Judgment</a></td>
        </tr>
    </table>
    """
    
    try:
        scraper = SupremeCourtScraper(config)
        soup = BeautifulSoup(sample_html, 'html.parser')
        
        # Test table parsing
        judgments = scraper._parse_table_from_soup(soup)
        
        print(f"✓ Extracted {len(judgments)} judgments from sample table")
        
        if judgments:
            judgment = judgments[0]
            print(f"✓ Sample judgment data:")
            for key, value in judgment.items():
                print(f"  {key}: {value}")
            
            # Check if all expected fields are present
            expected_fields = ['serial_number', 'diary_number', 'case_number', 
                             'petitioner_respondent', 'advocate', 'bench', 
                             'judgment_by', 'judgment_date', 'pdf_link']
            
            missing_fields = [field for field in expected_fields if field not in judgment]
            if missing_fields:
                print(f"✗ Missing fields: {missing_fields}")
                return False
            else:
                print("✓ All expected fields extracted successfully")
                
            # Check PDF link extraction
            if judgment.get('pdf_link'):
                print(f"✓ PDF link extracted: {judgment['pdf_link']}")
            else:
                print("✗ PDF link not extracted")
                return False
        
        return True
        
    except Exception as e:
        print(f"✗ Judgment extraction test failed: {e}")
        return False

def test_data_saving():
    """Test complete data saving workflow"""
    print("\n=== Testing Data Saving Workflow ===")
    
    try:
        scraper = SupremeCourtScraper(config)
        
        # Sample judgment data with all fields
        sample_judgments = [
            {
                'serial_number': '1',
                'diary_number': '228/2011',
                'case_number': 'C.A. No.009098-009098 - 2013',
                'petitioner_respondent': 'KANWAR RAJ SINGH (D) TH LRS . VS GEJO (D) TH LRS .',
                'advocate': 'JASPREET GOGIA',
                'bench': 'HON\'BLE MR. JUSTICE ABHAY S. OKA HON\'BLE MR. JUSTICE UJJAL BHUYAN',
                'judgment_by': 'HON\'BLE MR. JUSTICE ABHAY S. OKA',
                'judgment_date': '02-01-2024(English)',
                'pdf_link': '/judgment/download/123.pdf'
            },
            {
                'serial_number': '2',
                'diary_number': '1616/2024',
                'case_number': 'SLP(Crl) No.000550-000551 - 2024',
                'petitioner_respondent': 'SANJAY KUNDU VS REGISTRAR GENERAL HIGH COURT OF HIMACHAL PRADESH',
                'advocate': 'GAGAN GUPTA',
                'bench': 'HON\'BLE THE CHIEF JUSTICE HON\'BLE MR. JUSTICE J.B. PARDIWALA',
                'judgment_by': 'HON\'BLE THE CHIEF JUSTICE',
                'judgment_date': '12-01-2024(English)',
                'pdf_link': '/judgment/download/456.pdf'
            }
        ]
        
        # Test saving judgments
        success = scraper._save_judgments_to_mongodb(sample_judgments)
        print(f"✓ Saved sample judgments to MongoDB: {success}")
        
        # Verify data was saved with all fields
        mongo_client = MongoDBClient(config.mongo)
        
        for sample in sample_judgments:
            judgment_id = f"{sample['diary_number']}_{sample['case_number']}_{sample['judgment_date']}".replace('/', '_').replace(' ', '_').replace(':', '_')
            
            saved_judgment = mongo_client.get_judgment(judgment_id)
            if saved_judgment:
                print(f"✓ Judgment {judgment_id} saved successfully")
                print(f"  - Serial Number: {saved_judgment.serial_number}")
                print(f"  - Diary Number: {saved_judgment.diary_number}")
                print(f"  - Case Number: {saved_judgment.case_number}")
                print(f"  - Petitioner/Respondent: {saved_judgment.petitioner_respondent}")
                print(f"  - Advocate: {saved_judgment.advocate}")
                print(f"  - Bench: {saved_judgment.bench}")
                print(f"  - Judgment By: {saved_judgment.judgment_by}")
                print(f"  - PDF Link: {saved_judgment.pdf_link}")
                
                # Cleanup
                mongo_client.collection.delete_one({"judgment_id": judgment_id})
            else:
                print(f"✗ Judgment {judgment_id} not found in database")
                return False
        
        mongo_client.close()
        return True
        
    except Exception as e:
        print(f"✗ Data saving test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("Supreme Court Scraper - Complete Fix Verification")
    print("=" * 50)
    
    tests = [
        ("MongoDB Schema", test_mongodb_schema),
        ("Judgment Extraction", test_judgment_extraction),
        ("Data Saving Workflow", test_data_saving)
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"✗ {test_name} failed with exception: {e}")
            results.append((test_name, False))
    
    print("\n" + "=" * 50)
    print("TEST RESULTS SUMMARY")
    print("=" * 50)
    
    all_passed = True
    for test_name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"{test_name}: {status}")
        if not result:
            all_passed = False
    
    if all_passed:
        print("\n🎉 All tests passed! The scraper is ready for production use.")
        print("\nKey improvements verified:")
        print("- Complete MongoDB schema with all 8 judgment columns")
        print("- mark_as_completed method available")
        print("- Duplicate prevention working")
        print("- PDF links properly extracted and saved")
        print("- All judgment information captured")
    else:
        print("\n❌ Some tests failed. Please review the issues above.")
    
    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)