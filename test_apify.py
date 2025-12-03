#!/usr/bin/env python3
"""Test script to debug Apify Leads Finder integration"""

import os
from dotenv import load_dotenv
from apify_client import ApifyClient

load_dotenv()

def test_apify():
    token = os.getenv('APIFY_TOKEN')
    if not token:
        print("❌ APIFY_TOKEN not found")
        return
    
    print(f"✅ Token found: {token[:15]}...")
    
    client = ApifyClient(token)
    
    # Minimal test input
    test_input = {
        'contact_location': ['United Kingdom'],
        'company_industry': ['saas'],
        'fetch_count': 3  # Just 3 leads for testing
    }
    
    print(f"\n📤 Running actor with input: {test_input}")
    
    try:
        run = client.actor('code_crafter/leads-finder').call(run_input=test_input)
        print(f"✅ Actor run started: {run['id']}")
        print(f"   Status: {run['status']}")
        
        # Get results
        dataset_id = run['defaultDatasetId']
        print(f"\n📊 Fetching results from dataset: {dataset_id}")
        
        results = []
        for item in client.dataset(dataset_id).iterate_items():
            results.append(item)
            
        print(f"✅ Retrieved {len(results)} items")
        
        if results:
            print(f"\n🔍 First result sample:")
            first = results[0]
            print(f"   Keys: {list(first.keys())[:15]}")
            print(f"   Full name: {first.get('full_name', 'N/A')}")
            print(f"   Email: {first.get('email', 'N/A')}")
            print(f"   Job title: {first.get('job_title', 'N/A')}")
            print(f"   Company: {first.get('company_name', 'N/A')}")
        else:
            print("⚠️  No results returned")
            
    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    test_apify()
