#!/usr/bin/env python3
"""
Script to fix existing MongoDB documents where judgment_links and pdf_links
are stored as strings instead of arrays.
"""

import ast
from mongodb_client import MongoDBClient
from config import config
from loguru import logger

def fix_array_fields():
    """Fix judgment_links and pdf_links fields that are stored as strings"""
    client = MongoDBClient(config.mongo)
    
    try:
        # Find all documents where judgment_links or pdf_links are strings
        documents = list(client.collection.find({
            "$or": [
                {"judgment_links": {"$type": "string"}},
                {"pdf_links": {"$type": "string"}}
            ]
        }))
        
        logger.info(f"Found {len(documents)} documents with string array fields")
        
        fixed_count = 0
        for doc in documents:
            updates = {}
            
            # Fix judgment_links if it's a string
            if isinstance(doc.get('judgment_links'), str):
                try:
                    # Parse the string representation of the array
                    judgment_links = ast.literal_eval(doc['judgment_links'])
                    if isinstance(judgment_links, list):
                        updates['judgment_links'] = judgment_links
                        logger.info(f"Fixed judgment_links for {doc['judgment_id']}")
                except (ValueError, SyntaxError) as e:
                    logger.warning(f"Could not parse judgment_links for {doc['judgment_id']}: {e}")
            
            # Fix pdf_links if it's a string
            if isinstance(doc.get('pdf_links'), str):
                try:
                    # Parse the string representation of the array
                    pdf_links = ast.literal_eval(doc['pdf_links'])
                    if isinstance(pdf_links, list):
                        updates['pdf_links'] = pdf_links
                        logger.info(f"Fixed pdf_links for {doc['judgment_id']}")
                except (ValueError, SyntaxError) as e:
                    logger.warning(f"Could not parse pdf_links for {doc['judgment_id']}: {e}")
            
            # Update the document if we have fixes
            if updates:
                result = client.collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": updates}
                )
                if result.modified_count > 0:
                    fixed_count += 1
                    logger.info(f"Updated document {doc['judgment_id']}")
        
        logger.info(f"Fixed {fixed_count} documents")
        
        # Verify the fix
        remaining = client.collection.count_documents({
            "$or": [
                {"judgment_links": {"$type": "string"}},
                {"pdf_links": {"$type": "string"}}
            ]
        })
        
        logger.info(f"Remaining documents with string array fields: {remaining}")
        
    except Exception as e:
        logger.error(f"Error fixing array fields: {e}")
    finally:
        client.close()

if __name__ == "__main__":
    fix_array_fields()