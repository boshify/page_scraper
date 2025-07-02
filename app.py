from flask import Flask, request, jsonify
import cloudscraper
from bs4 import BeautifulSoup
import random
import os

app = Flask(__name__)

# User-Agent list for randomization
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/15.3 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:92.0) Gecko/20100101 Firefox/92.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.101 Safari/537.36",
]

def get_random_user_agent():
    return random.choice(USER_AGENTS)

@app.route('/')
def home():
    return "Scraper API is running."

@app.route('/read', methods=['POST'])
def read_page():
    url = request.json.get('url')
    if not url or not url.startswith("http"):
        return jsonify({'error': 'Invalid or missing URL', 'url': url}), 400

    # Create scraper session with random User-Agent
    scraper = cloudscraper.create_scraper()
    headers = {
        "User-Agent": get_random_user_agent(),
        "Referer": "https://www.google.com",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        response = scraper.get(url, headers=headers, timeout=10)
        status = response.status_code

        if status != 200:
            return jsonify({'error': f"HTTP error {status}", 'url': url}), 502

        html = response.text
        if not html or len(html) < 1000:
            return jsonify({'error': 'Empty or suspicious page', 'url': url}), 500

        soup = BeautifulSoup(html, 'html.parser')
        main = soup.find('article') or soup.find('main') or soup.find('body')
        text = main.get_text(separator='\n').strip() if main else soup.get_text().strip()

        if not text or len(text) < 200:
            return jsonify({'error': 'Failed to extract meaningful content', 'url': url}), 500

        # Limit content to prevent overload
        return jsonify({
            'url': url,
            'content': text[:5000],
            'length': len(text)
        })

    except Exception as e:
        return jsonify({'error': str(e), 'url': url}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
