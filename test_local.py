#!/usr/bin/env python3
"""Test script for local page scraper"""
import requests
import json

# Test URLs
TEST_URLS = [
    {
        "name": "Test 1 (easy)",
        "url": "https://jonathanboshoff.com/about-me/",
    },
    {
        "name": "Test 2 (hard)",
        "url": "https://www.tealhq.com/post/how-to-get-your-resume-past-ai",
    }
]

def test_local(url):
    """Test against local server"""
    endpoint = "http://localhost:5000/read"
    payload = {
        "url": url,
        "max_chars": 10000,
        "return_html": False
    }

    try:
        response = requests.post(endpoint, json=payload, timeout=60)
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def main():
    print("=" * 80)
    print("TESTING LOCAL DEPLOYMENT")
    print("=" * 80)

    for test in TEST_URLS:
        print(f"\n{test['name']}: {test['url']}")
        print("-" * 80)
        result = test_local(test['url'])

        if "error" in result:
            print(f"[ERROR] {result['error']}")
        elif result.get("ok"):
            print(f"[SUCCESS]")
            print(f"   Title: {result.get('title', 'N/A')}")
            print(f"   Length: {result.get('length', 0)} chars")
            print(f"   Sections: {len(result.get('outline_sections', []))}")
            if result.get('flat_outline'):
                preview = result['flat_outline'][:300].replace('\n', ' ')
                print(f"   Preview: {preview}...")
        else:
            print(f"[FAILED] {result.get('message', 'Unknown error')}")
            print(f"   Reason: {result.get('reason', 'N/A')}")
            print(f"   HTTP Status: {result.get('http_status', 'N/A')}")

if __name__ == "__main__":
    main()
