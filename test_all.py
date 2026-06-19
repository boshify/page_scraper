#!/usr/bin/env python3
"""Test script for all 3 target URLs"""
import requests
import json

# Test URLs from requirements
TEST_URLS = [
    {
        "name": "GTO Wizard Blog",
        "url": "https://blog.gtowizard.com/the-science-of-poker-performance/",
    },
    {
        "name": "Teal HQ Blog",
        "url": "https://www.tealhq.com/post/how-to-get-your-resume-past-ai",
    },
    {
        "name": "Jonathan Boshoff About",
        "url": "https://jonathanboshoff.com/about-me/",
    }
]

def test_local(url):
    """Test against local server"""
    endpoint = "http://localhost:5000/read"
    payload = {
        "url": url,
        "max_chars": 20000,
        "return_html": True,
        "clean_html": True
    }

    try:
        response = requests.post(endpoint, json=payload, timeout=60)
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def analyze_corruption(result):
    """Analyze if the result shows signs of corruption"""
    issues = []

    if not result.get("ok"):
        issues.append(f"Failed to scrape: {result.get('message', 'Unknown')}")
        return issues

    # Check for very short content
    length = result.get('length', 0)
    if length < 100:
        issues.append(f"Content too short ({length} chars)")

    # Check for missing title
    if not result.get('title'):
        issues.append("Missing title")

    # Check for missing sections
    sections = result.get('outline_sections', [])
    if len(sections) < 2:
        issues.append(f"Too few sections ({len(sections)})")

    # Check for garbled text patterns
    flat_outline = result.get('flat_outline', '')
    if flat_outline:
        # Look for encoding issues - use Unicode codepoint to avoid printing issue
        if '\ufffd' in flat_outline:
            issues.append("Found replacement characters (encoding issue)")
        if flat_outline.count('\n') < 5 and length > 500:
            issues.append("Too few line breaks (possible formatting issue)")

    return issues

def main():
    print("=" * 80)
    print("TESTING ALL 3 TARGET URLs")
    print("=" * 80)

    results = []
    for test in TEST_URLS:
        print(f"\n{test['name']}")
        print(f"URL: {test['url']}")
        print("-" * 80)
        result = test_local(test['url'])

        if "error" in result:
            print(f"[ERROR] {result['error']}")
            results.append({"name": test['name'], "status": "error", "issues": [result['error']]})
        elif result.get("ok"):
            issues = analyze_corruption(result)
            if issues:
                print(f"[PARTIAL] Scraped but has issues:")
                for issue in issues:
                    print(f"   - {issue}")
                results.append({"name": test['name'], "status": "partial", "issues": issues})
            else:
                print(f"[SUCCESS]")

            print(f"   Title: {result.get('title', 'N/A')}")
            print(f"   Length: {result.get('length', 0):,} chars")
            print(f"   Sections: {len(result.get('outline_sections', []))}")
            print(f"   Tables: {len(result.get('tables', []))}")

            if result.get('flat_outline'):
                preview = result['flat_outline'][:400].replace('\n', ' ')
                print(f"   Preview: {preview}...")

            if not issues:
                results.append({"name": test['name'], "status": "success", "issues": []})
        else:
            print(f"[FAILED] {result.get('message', 'Unknown error')}")
            print(f"   Reason: {result.get('reason', 'N/A')}")
            print(f"   HTTP Status: {result.get('http_status', 'N/A')}")
            results.append({"name": test['name'], "status": "failed", "issues": [result.get('message')]})

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    success_count = sum(1 for r in results if r['status'] == 'success')
    print(f"Successful: {success_count}/3")

    for r in results:
        if r['status'] != 'success':
            print(f"\n{r['name']}: {r['status'].upper()}")
            for issue in r['issues']:
                print(f"  - {issue}")

if __name__ == "__main__":
    main()
