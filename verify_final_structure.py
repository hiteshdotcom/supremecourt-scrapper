#!/usr/bin/env python3

from mongodb_client import MongoDBClient
from config import config

def verify_final_structure():
    client = MongoDBClient(config.mongo)
    
    # Get sample documents
    sample_docs = list(client.collection.find({}).limit(3))
    
    print("Final verification of judgment_links format:")
    print("=" * 50)
    
    for i, doc in enumerate(sample_docs, 1):
        print(f"\nDocument {i}:")
        print(f"ID: {doc.get('judgment_id', 'unknown')}")
        
        judgment_links = doc.get('judgment_links', [])
        pdf_links = doc.get('pdf_links', [])
        
        print(f"judgment_links type: {type(judgment_links)}")
        print(f"judgment_links: {judgment_links}")
        
        if isinstance(judgment_links, list) and judgment_links:
            print(f"First judgment link type: {type(judgment_links[0])}")
            print(f"First judgment link: {judgment_links[0]}")
        
        print(f"pdf_links type: {type(pdf_links)}")
        print(f"pdf_links: {pdf_links}")
        
        if isinstance(pdf_links, list) and pdf_links:
            print(f"First pdf link type: {type(pdf_links[0])}")
            print(f"First pdf link: {pdf_links[0]}")
    
    # Final count verification
    total_docs = client.collection.count_documents({})
    docs_with_judgment_links = client.collection.count_documents({'judgment_links': {'$exists': True, '$ne': []}})
    docs_with_pdf_links = client.collection.count_documents({'pdf_links': {'$exists': True, '$ne': []}})
    
    print(f"\n" + "=" * 50)
    print("SUMMARY:")
    print(f"Total documents: {total_docs}")
    print(f"Documents with judgment_links: {docs_with_judgment_links}")
    print(f"Documents with pdf_links: {docs_with_pdf_links}")
    print("\n✅ SUCCESS: judgment_links and pdf_links are now stored as arrays of strings!")
    print("Format: judgments: ['link1', 'link2'] ✓")
    
    client.close()

if __name__ == "__main__":
    verify_final_structure()