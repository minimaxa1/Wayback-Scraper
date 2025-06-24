# scrape_ai_articles.py
import requests
from bs4 import BeautifulSoup
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
    "spectrum.ieee.org" # Good for more academic/deep tech
]
AI_KEYWORDS = ["artificial intelligence", "ai", "machine learning", "deep learning", "neural network", "robotics", "nlp", "computer vision"]
DATA_FILE = "ai_articles.json"
IMAGES_DIR = "images/ai_time_capsule"
MAX_ARTICLES_PER_RUN = 5 # How many new AI articles to try and add per run
PAST_YEAR_RANGE = (2000, 2015) # Dates to search within (e.g., peak early AI discussions)
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
    random_number_of_days = random.randrange(days_between_dates)
    random_date = start_date + timedelta(days=random_number_of_days)
    return random_date

def fetch_wayback_snapshots(domain, date_str, limit=500):
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
        response = requests.get(WAYBACK_CDX_API, params=params, timeout=10)
        response.raise_for_status() # Raise an exception for HTTP errors
        data = response.json()
        
        # CDX API returns header as first element, skip it
        if data and data[0] and data[0][0] == 'urlkey':
            data = data[1:]
        
        snapshots = []
        for record in data:
            original_url = record[2]
            timestamp = record[1]
            # Construct the Wayback Machine playback URL
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
        img_data = requests.get(image_url, timeout=5).content
        img = Image.open(io.BytesIO(img_data))
        
        # Convert to RGB if not, for WebP compatibility
        if img.mode == 'P' or img.mode == 'LA' or img.mode == 'RGBA':
            img = img.convert('RGB')

        img.thumbnail((300, 200), Image.Resampling.LANCZOS) # Resize: 300x200 max, maintaining aspect ratio
        
        image_filename = f"{article_id}.webp"
        image_filepath = os.path.join(IMAGES_DIR, image_filename)
        img.save(image_filepath, "webp", quality=75) # Compress to webp
        return image_filepath
    except Exception as e:
        logging.warning(f"Could not process image {image_url}: {e}")
        return None

def is_ai_relevant(title, text):
    """Checks if the article title or text contains AI-related keywords."""
    for keyword in AI_KEYWORDS:
        if keyword in title.lower() or keyword in text.lower():
            return True
    return False

def scrape_article(wayback_url, original_url, article_id):
    """Scrapes a single article using newspaper3k and processes it."""
    try:
        article = newspaper.Article(wayback_url)
        article.download()
        article.parse()
        
        if not article.title or not article.text or len(article.text) < 100: # Minimal content validation
            logging.info(f"Skipping {wayback_url}: Missing title or too short content.")
            return None

        # Filter for AI relevance AFTER parsing
        if not is_ai_relevant(article.title, article.text):
            logging.info(f"Skipping {wayback_url}: Not AI relevant.")
            return None

        summary = ' '.join(article.text.split()[:80]) + '...' if article.text else '' # Longer summary

        image_path = None
        if article.top_image:
            image_path = process_image(article.top_image, article_id)
        
        return {
            "id": article_id, # Unique ID for each article
            "title": article.title,
            "summary": summary,
            "original_url": original_url,
            "wayback_url": wayback_url,
            "image_path": image_path.replace("\\", "/") if image_path else None, # For consistent URL paths on web
            "publish_date": article.publish_date.isoformat() if article.publish_date else datetime.now().isoformat(),
            "source": original_url.split('/')[2] # e.g., techcrunch.com
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
    
    while articles_added_this_run < MAX_ARTICLES_PER_RUN and attempts < 100: # Limit attempts to prevent infinite loops
        attempts += 1
        target_date = get_random_past_date(*PAST_YEAR_RANGE)
        target_date_str = target_date.strftime("%Y%m%d")
        logging.info(f"Attempting to find articles for: {target_date.strftime('%Y-%m-%d')}")
        
        random.shuffle(TARGET_DOMAINS) # Randomize domain order for variety
        
        for domain in TARGET_DOMAINS:
            if articles_added_this_run >= MAX_ARTICLES_PER_RUN:
                break # Stop if we've found enough
            
            snapshots = fetch_wayback_snapshots(domain, target_date_str, limit=50) # Increased limit for more candidates
            if not snapshots:
                continue

            random.shuffle(snapshots) # Shuffle snapshots to avoid always picking the same ones
            
            for snap in snapshots:
                if articles_added_this_run >= MAX_ARTICLES_PER_RUN:
                    break
                if snap['original_url'] in existing_original_urls:
                    logging.info(f"Skipping already processed: {snap['original_url']}")
                    continue
                
                # Pre-filter by URL/Title guess for basic AI keywords
                potential_ai = False
                for keyword in AI_KEYWORDS:
                    if keyword in snap['original_url'].lower() or keyword in snap['title_guess'].lower():
                        potential_ai = True
                        break
                if not potential_ai:
                    logging.debug(f"Skipping {snap['original_url']}: No immediate AI keywords in URL/guessed title.")
                    continue

                article_id = f"{len(existing_articles) + articles_added_this_run}_{random.randint(1000,9999)}" # Simple unique ID
                article_data = scrape_article(snap['wayback_url'], snap['original_url'], article_id)
                
                if article_data:
                    existing_articles.append(article_data)
                    existing_original_urls.add(snap['original_url'])
                    articles_added_this_run += 1
                    logging.info(f"Added article: {article_data['title']} (from {article_data['source']} on {target_date.strftime('%Y-%m-%d')})")
                    if articles_added_this_run >= MAX_ARTICLES_PER_RUN:
                        break # Exit inner loop if max reached
                
                time.sleep(1) # Be polite to Wayback Machine
        
        time.sleep(2) # Pause between different random date attempts

    save_articles(existing_articles)
    logging.info(f"Finished. Added {articles_added_this_run} new articles. Total articles: {len(existing_articles)}")

if __name__ == "__main__":
    main()