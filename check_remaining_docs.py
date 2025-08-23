#!/usr/bin/env python3

from mongodb_client import MongoDBClient
from config import config

def check_remaining_docs():
    client = MongoDBClient(config.mongo)
    
    # Find documents with string array fields
    docs = list(client.collection.find({
        '$or': [
            {'judgment_links': {'$type': 'string'}}, 
            {'pdf_links': {'$type': 'string'}}
        ]
    }).limit(3))
    
    print(f"Found {len(docs)} documents with string fields:")
    
    for i, doc in enumerate(docs):
        print(f"\nDocument {i+1}:")
        print(f"ID: {doc.get('judgment_id', 'unknown')}")
        
        judgment_links = doc.get('judgment_links')
        pdf_links = doc.get('pdf_links')
        
        print(f"judgment_links type: {type(judgment_links)}")
        print(f"judgment_links value: {repr(judgment_links)}")
        print(f"pdf_links type: {type(pdf_links)}")
        print(f"pdf_links value: {repr(pdf_links)}")
        
        # Try to see if it's a valid list string
        if isinstance(judgment_links, str):
            try:
                import ast
                parsed = ast.literal_eval(judgment_links)
                print(f"judgment_links can be parsed as: {type(parsed)} - {parsed}")
            except Exception as e:
                print(f"judgment_links parsing error: {e}")
                
        if isinstance(pdf_links, str):
            try:
                import ast
                parsed = ast.literal_eval(pdf_links)
                print(f"pdf_links can be parsed as: {type(parsed)} - {parsed}")
            except Exception as e:
                print(f"pdf_links parsing error: {e}")
    
    client.close()

if __name__ == "__main__":
    check_remaining_docs()