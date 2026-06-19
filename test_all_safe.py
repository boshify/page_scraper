#!/usr/bin/env python3
"""Test script for all 3 target URLs - safe version that writes to file"""
import requests
import json
import sys

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
        # Look for encoding issues
        if '\ufffd' in flat_outline:
            issues.append("Found replacement characters (encoding issue)")
        if flat_outline.count('\n') < 5 and length > 500:
            issues.append("Too few line breaks (possible formatting issue)")

    return issues

def main():
    output = []
    output.append("=" * 80)
    output.append("TESTING ALL 3 TARGET URLs")
    output.append("=" * 80)

    results = []
    for test in TEST_URLS:
        output.append(f"\n{test['name']}")
        output.append(f"URL: {test['url']}")
        output.append("-" * 80)
        result = test_local(test['url'])

        if "error" in result:
            output.append(f"[ERROR] {result['error']}")
            results.append({"name": test['name'], "status": "error", "issues": [result['error']]})
        elif result.get("ok"):
            issues = analyze_corruption(result)
            if issues:
                output.append(f"[PARTIAL] Scraped but has issues:")
                for issue in issues:
                    output.append(f"   - {issue}")
                results.append({"name": test['name'], "status": "partial", "issues": issues})
            else:
                output.append(f"[SUCCESS]")

            output.append(f"   Title: {result.get('title', 'N/A')}")
            output.append(f"   Length: {result.get('length', 0):,} chars")
            output.append(f"   Sections: {len(result.get('outline_sections', []))}")
            output.append(f"   Tables: {len(result.get('tables', []))}")

            if result.get('flat_outline'):
                # Safely encode preview to ASCII for console
                preview = result['flat_outline'][:400].replace('\n', ' ')
                try:
                    preview_safe = preview.encode('ascii', errors='replace').decode('ascii')
                except:
                    preview_safe = "[Preview contains non-ASCII chars]"
                output.append(f"   Preview: {preview_safe}...")

            if not issues:
                results.append({"name": test['name'], "status": "success", "issues": []})

            # Save full result to file for inspection
            with open(f"test_result_{test['name'].replace(' ', '_').lower()}.json", "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
        else:
            output.append(f"[FAILED] {result.get('message', 'Unknown error')}")
            output.append(f"   Reason: {result.get('reason', 'N/A')}")
            output.append(f"   HTTP Status: {result.get('http_status', 'N/A')}")
            results.append({"name": test['name'], "status": "failed", "issues": [result.get('message')]})

    # Summary
    output.append("\n" + "=" * 80)
    output.append("SUMMARY")
    output.append("=" * 80)
    success_count = sum(1 for r in results if r['status'] == 'success')
    output.append(f"Successful: {success_count}/3")

    for r in results:
        if r['status'] != 'success':
            output.append(f"\n{r['name']}: {r['status'].upper()}")
            for issue in r['issues']:
                output.append(f"  - {issue}")

    # Write to file
    with open("test_results.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(output))

    # Print safely to console
    for line in output:
        try:
            print(line)
        except UnicodeEncodeError:
            print(line.encode('ascii', errors='replace').decode('ascii'))

if __name__ == "__main__":
    main()
