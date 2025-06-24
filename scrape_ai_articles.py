# scrape_ai_articles.py (Fourth Revision: Targeted Domains)
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
    # Top candidates based on your search results, starting earlier or being very relevant
    "kurzweilai.net",       # Excellent candidate, captures from 2001
    "ai-depot.com",         # Excellent candidate, captures from 2001
    "generation5.org",      # Good candidate, captures from 2000
    "sciencedaily.com",     # Captures from 1996, broad science news, likely some AI
    "alife.org",            # International Society of Artificial Life, captures from 1998, highly relevant
    "inform.com",           # Captures from 1998, broader news platform, might have AI

    # Other relevant candidates from your list (some might start later or be niche)
    "phys.org",             # Science news, captures from 2002
    "esciencenews.com",     # Science news, captures from 2008
    "aihub.org",            # AI focused, captures from 2008
    "agi-08.org",           # Specific conference, captures from 2007, might have papers
    "vieartificielle.com",  # AI focused, captures from 2001
    "newstrove.com",        # News aggregator, captures from 2000
    "silobreaker.com",      # News aggregator, captures from 2005
    "gamedev.net",          # Game AI might be present, captures from 1999
    "oreillynet.com",       # O'Reilly technical content, captures from 2000
    "advogato.org",         # Open source tech community, captures from 1999
    "webindia123.com",      # General news portal, captures from 2000 (lower relevance chance)
    "nursingtimes.net",     # Unlikely, but AI in health tech could exist
    "psychology.about.com", # Psychology of AI? Unlikely direct news, but possible
    
    # Original domains that might still contribute to later years
    "wired.com",            # Captures from 1993, good for late 90s onwards
    "cnet.com",             # Captures from 1994, good for late 90s onwards
    "arstechnica.com",      # Captures from 1998, good for late 90s onwards
    "spectrum.ieee.org",    # Good for more academic/deep tech, older captures
]

AI_KEYWORDS = ["artificial intelligence", "ai", "machine learning", "deep learning", "neural network", "robotics", "nlp", "computer vision", "AGI", "Cyber", "Cyberpunk", "Virtual reality"] # Added AGI
DATA_FILE = "ai_articles.json"
IMAGES_DIR = "images/ai_time_capsule"

# --- IMPORTANT CHANGES FOR DATE RANGE AND TIMEOUTS ---
MAX_ARTICLES_PER_RUN = 1  # Aim for just 1 article per successful run, to maximize completion
MAX_DAILY_ATTEMPTS = 150  # Increased attempts, as the new domains are more likely to have hits
REQUEST_TIMEOUT = 30      # Keep increased timeout for network requests
# Adjusted: Start with a range that many of your found domains are active in
PAST_YEAR_RANGE = (1980, 2000) 
WAYBACK_CDX_API = "http://web.archive.org/cdx/search/cdx"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

os.makedirs(IMAGES_DIR, exist_ok=True)

def get_random_past_date(start_year, end_year):
    start_date = datetime(start_year, 1, 1)
    end_date = datetime(end_year + 1, 1, 1) - timedelta(days=1)
    
    time_between_dates = end_date - start_date
    # CORRECTED LINE HERE:
    days_between_dates = time_between_dates.days 
    
    if days_between_dates <= 0:
        logging.warning(f"Invalid date range for random date generation: {start_year}-{end_year}")
        return start_date
    random_number_of_days = random.randrange(days_between_dates)
    random_date = start_date + timedelta(days=random_number_of_days)
    return random_date

def fetch_wayback_snapshots(domain, date_str, limit=50):
    params = {
        "url": f"{domain}/*", # Query for all URLs under the domain
        "from": date_str,
        "to": date_str,
        "limit": limit,
        "output": "json",
        "collapse": "urlkey", 
        "filter": ["statuscode:200", "!mimetype:image/jpeg", "!mimetype:image/png"],
    }
    
    try:
        logging.info(f"  Querying CDX for {domain} on {date_str}...")
        response = requests.get(WAYBACK_CDX_API, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status() 
        data = response.json()
        
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
                "title_guess": original_url.split('/')[-2].replace('-', ' ').title() if len(original_url.split('/')) > 2 and original_url.split('/')[-2] else ""
            })
        return snapshots
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching CDX snapshots for {domain} on {date_str}: {e}")
        return []
    except json.JSONDecodeError as e:
        logging.error(f"JSON decode error for CDX response from {domain} on {date_str}: {e}. Response: {response.text[:200]}...")
        return []


def process_image(image_url, article_id):
    try:
        img_data = requests.get(image_url, timeout=REQUEST_TIMEOUT).content
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
    title_lower = title.lower()
    text_lower = text.lower()
    for keyword in AI_KEYWORDS:
        if keyword in title_lower or keyword in text_lower:
            return True
    return False

def scrape_article(wayback_url, original_url, article_id):
    try:
        config = newspaper.Config()
        config.browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        config.request_timeout = REQUEST_TIMEOUT

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
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                logging.warning(f"Corrupt or empty {DATA_FILE}, starting fresh.")
                return []
    return []

def save_articles(articles):
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
            snapshots = fetch_wayback_snapshots(domain, target_date_str, limit=50) 
            if not snapshots:
                logging.info(f"  No snapshots found for {domain} on {target_date_str}.")
                time.sleep(1) 
                continue

            random.shuffle(snapshots)
            
            for i, snap in enumerate(snapshots):
                if articles_added_this_run >= MAX_ARTICLES_PER_RUN:
                    break
                if snap['original_url'] in existing_original_urls:
                    logging.debug(f"  Skipping already processed: {snap['original_url']}")
                    continue
                
                potential_ai = False
                if any(keyword in snap['original_url'].lower() for keyword in AI_KEYWORDS):
                    potential_ai = True
                elif any(keyword in snap['title_guess'].lower() for keyword in AI_KEYWORDS):
                     potential_ai = True

                if not potential_ai:
                    logging.debug(f"  Skipping {snap['original_url']}: No immediate AI keywords in URL/guessed title.")
                    continue

                logging.info(f"  Attempting to scrape {i+1}/{len(snapshots)} potential AI articles from {domain}: {snap['original_url']}")
                article_id = f"{len(existing_articles) + articles_added_this_run}_{random.randint(1000,9999)}"
                article_data = scrape_article(snap['wayback_url'], snap['original_url'], article_id)
                
                if article_data:
                    existing_articles.append(article_data)
                    existing_original_urls.add(snap['original_url'])
                    articles_added_this_run += 1
                    logging.info(f"  SUCCESS: Added '{article_data['title']}' ({article_data['source']} from {target_date.strftime('%Y-%m-%d')})")
                    if articles_added_this_run >= MAX_ARTICLES_PER_RUN:
                        break
                
                time.sleep(2) 

        time.sleep(5) 
        
    save_articles(existing_articles)
    logging.info(f"Finished run. Added {articles_added_this_run} new articles. Total articles in file: {len(existing_articles)}")

if __name__ == "__main__":
    main()
