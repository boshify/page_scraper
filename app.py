from flask import Flask, request, jsonify
import cloudscraper
from bs4 import BeautifulSoup

app = Flask(__name__)

@app.route('/read', methods=['POST'])
def read_page():
    url = request.json.get('url')
    if not url:
        return jsonify({'error': 'Missing URL'}), 400

    scraper = cloudscraper.create_scraper()
    try:
        response = scraper.get(url, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')

        # Try to extract article/main/body content
        main = soup.find('article') or soup.find('main') or soup.find('body')
        text = main.get_text(separator='\n').strip() if main else soup.get_text().strip()

        return jsonify({
            'url': url,
            'content': text[:5000]  # limit for OpenAI input
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
