# scrape_ai_articles.py (Updated Version)
import requests
from bs4 import BeautifulSoup # Keep for potential future use, though newspaper3k handles most
import newspaper
import os
import json
from PIL import Image
import io
import time
import random
from datetime import datetime, timedelta
import logging

# --- Configuration ---
TARGET_DOMAINS = [
    "techcrunch.com",
    "engadget.com",
    "wired.com",
    "arstechnica.com",
    "cnet.com",
    "spectrum.ieee.org"
]
AI_KEYWORDS = ["artificial intelligence", "ai", "machine learning", "deep learning", "neural network", "robotics", "nlp", "computer vision"]
DATA_FILE = "ai_articles.json"
IMAGES_DIR = "images/ai_time_capsule"
# --- IMPORTANT CHANGES FOR TIMEOUTS ---
MAX_ARTICLES_PER_RUN = 2  # Reduced to add fewer articles per run, making it faster to complete
MAX_DAILY_ATTEMPTS = 50   # Reduced max attempts to find articles for a given day.
REQUEST_TIMEOUT = 15      # Timeout for network requests in seconds
PAST_YEAR_RANGE = (2005, 2015) # Focused date range for initial testing, adjust later
WAYBACK_CDX_API = "http://web.archive.org/cdx/search/cdx"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Ensure directories exist
os.makedirs(IMAGES_DIR, exist_ok=True)

def get_random_past_date(start_year, end_year):
    """Generates a random date within the specified year range."""
    start_date = datetime(start_year, 1, 1)
    end_date = datetime(end_year + 1, 1, 1) - timedelta(days=1)
    
    time_between_dates = end_date - start_date
    days_between_dates = time_between_dates.days
    if days_between_dates <= 0: # Handle cases where range is too small or invalid
        return start_date # Fallback to start date
    random_number_of_days = random.randrange(days_between_dates)
    random_date = start_date + timedelta(days=random_number_of_days)
    return random_date

def fetch_wayback_snapshots(domain, date_str, limit=100): # Reduced limit from 500 to 100
    """Fetches potential Wayback Machine snapshots for a domain on a specific date."""
    params = {
        "url": f"{domain}/*",
        "from": date_str,
        "to": date_str,
        "limit": limit,
        "output": "json",
        "collapse": "urlkey", # Get unique URLs
        "filter": ["statuscode:200", "!mimetype:image/jpeg", "!mimetype:image/png"], # Only successful HTML pages
    }
    
    try:
        response = requests.get(WAYBACK_CDX_API, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status() # Raise an exception for HTTP errors
        data = response.json()
        
        # CDX API returns header as first element, skip it
        if data and data[0] and data[0][0] == 'urlkey':
            data = data[1:]
        
        snapshots = []
        for record in data:
            original_url = record[2]
            timestamp = record[1]
            wayback_url = f"http://web.archive.org/web/{timestamp}/{original_url}"
            snapshots.append({
                "original_url": original_url,
                "wayback_url": wayback_url,
                "timestamp": timestamp,
                "title_guess": original_url.split('/')[-2].replace('-', ' ').title() if original_url.split('/')[-2] else "" # Basic title guess from URL
            })
        return snapshots
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching CDX snapshots for {domain} on {date_str}: {e}")
        return []

def process_image(image_url, article_id):
    """Downloads, resizes, compresses, and saves an image."""
    try:
        img_data = requests.get(image_url, timeout=REQUEST_TIMEOUT).content # Added timeout
        img = Image.open(io.BytesIO(img_data))
        
        if img.mode == 'P' or img.mode == 'LA' or img.mode == 'RGBA':
            img = img.convert('RGB')

        img.thumbnail((300, 200), Image.Resampling.LANCZOS)
        
        image_filename = f"{article_id}.webp"
        image_filepath = os.path.join(IMAGES_DIR, image_filename)
        img.save(image_filepath, "webp", quality=75)
        return image_filepath
    except Exception as e:
        logging.warning(f"Could not process image {image_url}: {e}")
        return None

def is_ai_relevant(title, text):
    """Checks if the article title or text contains AI-related keywords."""
    title_lower = title.lower()
    text_lower = text.lower()
    for keyword in AI_KEYWORDS:
        if keyword in title_lower or keyword in text_lower:
            return True
    return False

def scrape_article(wayback_url, original_url, article_id):
    """Scrapes a single article using newspaper3k and processes it."""
    try:
        # Configure newspaper to use the request timeout
        config = newspaper.Config()
        config.browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        config.request_timeout = REQUEST_TIMEOUT # Pass timeout to newspaper3k

        article = newspaper.Article(wayback_url, config=config)
        article.download()
        article.parse()
        
        if not article.title or not article.text or len(article.text) < 100:
            logging.info(f"Skipping {wayback_url}: Missing title or too short content.")
            return None

        if not is_ai_relevant(article.title, article.text):
            logging.info(f"Skipping {wayback_url}: Not AI relevant.")
            return None

        summary = ' '.join(article.text.split()[:80]) + '...' if article.text else ''

        image_path = None
        if article.top_image:
            image_path = process_image(article.top_image, article_id)
        
        return {
            "id": article_id,
            "title": article.title,
            "summary": summary,
            "original_url": original_url,
            "wayback_url": wayback_url,
            "image_path": image_path.replace("\\", "/") if image_path else None,
            "publish_date": article.publish_date.isoformat() if article.publish_date else datetime.now().isoformat(),
            "source": original_url.split('/')[2]
        }
    except newspaper.article.ArticleException as e:
        logging.warning(f"Newspaper3k error processing {wayback_url}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        logging.warning(f"Request error fetching {wayback_url}: {e}")
        return None
    except Exception as e:
        logging.error(f"General error processing {wayback_url}: {e}")
        return None

def load_existing_articles():
    """Loads existing articles from the JSON file."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                logging.warning(f"Corrupt or empty {DATA_FILE}, starting fresh.")
                return []
    return []

def save_articles(articles):
    """Saves the updated list of articles to the JSON file."""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(articles, f, indent=2, ensure_ascii=False)

def main():
    existing_articles = load_existing_articles()
    existing_original_urls = {a['original_url'] for a in existing_articles}
    
    articles_added_this_run = 0
    attempts = 0
    
    logging.info("Starting Wayback AI Time Capsule scraping run...")
    
    while articles_added_this_run < MAX_ARTICLES_PER_RUN and attempts < MAX_DAILY_ATTEMPTS:
        attempts += 1
        target_date = get_random_past_date(*PAST_YEAR_RANGE)
        target_date_str = target_date.strftime("%Y%m%d")
        logging.info(f"Attempt {attempts}/{MAX_DAILY_ATTEMPTS}: Searching for articles from: {target_date.strftime('%Y-%m-%d')}")
        
        random.shuffle(TARGET_DOMAINS)
        
        for domain in TARGET_DOMAINS:
            if articles_added_this_run >= MAX_ARTICLES_PER_RUN:
                break
            
            logging.info(f"  Fetching snapshots from {domain}...")
            snapshots = fetch_wayback_snapshots(domain, target_date_str, limit=50) # Use a lower limit for CDX API requests
            if not snapshots:
                logging.info(f"  No snapshots found for {domain} on {target_date_str}.")
                continue

            random.shuffle(snapshots)
            
            for i, snap in enumerate(snapshots):
                if articles_added_this_run >= MAX_ARTICLES_PER_RUN:
                    break
                if snap['original_url'] in existing_original_urls:
                    logging.debug(f"  Skipping already processed: {snap['original_url']}")
                    continue
                
                # Pre-filter by URL/Title guess for basic AI keywords
                potential_ai = False
                for keyword in AI_KEYWORDS:
                    if keyword in snap['original_url'].lower() or keyword in snap['title_guess'].lower():
                        potential_ai = True
                        break
                if not potential_ai:
                    logging.debug(f"  Skipping {snap['original_url']}: No immediate AI keywords in URL/guessed title.")
                    continue

                logging.info(f"  Attempting to scrape {i+1}/{len(snapshots)} from {domain}: {snap['original_url']}")
                article_id = f"{len(existing_articles) + articles_added_this_run}_{random.randint(1000,9999)}"
                article_data = scrape_article(snap['wayback_url'], snap['original_url'], article_id)
                
                if article_data:
                    existing_articles.append(article_data)
                    existing_original_urls.add(snap['original_url'])
                    articles_added_this_run += 1
                    logging.info(f"  SUCCESS: Added '{article_data['title']}' ({article_data['source']} from {target_date.strftime('%Y-%m-%d')})")
                    if articles_added_this_run >= MAX_ARTICLES_PER_RUN:
                        break # Exit inner loop if max reached
                
                time.sleep(1.5) # Be more polite to Wayback Machine between article fetches

        time.sleep(3) # Longer pause between different random date attempts / domains
        
    save_articles(existing_articles)
    logging.info(f"Finished run. Added {articles_added_this_run} new articles. Total articles in file: {len(existing_articles)}")

if __name__ == "__main__":
    main()
