# scrape_ai_articles.py (Rebuilt for Google Custom Search JSON API)
import requests
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
# You must set these as GitHub Secrets
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")  # Your Google Cloud API Key
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")    # Your Custom Search Engine ID

GOOGLE_CSE_API_URL = "https://www.googleapis.com/customsearch/v1"

AI_KEYWORDS = ["artificial intelligence", "ai", "machine learning", "deep learning", "neural network", "robotics", "nlp", "computer vision", "AGI", "Cyber", "VR", "Cyberpunk,]
DATA_FILE = "ai_articles.json"
IMAGES_DIR = "images/ai_time_capsule"

MAX_ARTICLES_PER_RUN = 3  # Aim for a few articles per run to keep usage manageable
MAX_SEARCH_ATTEMPTS = 50  # Max attempts to find a suitable random month/year with results
REQUEST_TIMEOUT = 15      # Timeout for network requests to live sites and articles

# Realistic range for good Google Search index coverage.
# Use 2000-2016 for better success rate initially.
PAST_YEAR_RANGE = (1990, 2016) 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

os.makedirs(IMAGES_DIR, exist_ok=True)

def get_random_past_month(start_year, end_year):
    """Generates a random month and year within the specified range."""
    year = random.randint(start_year, end_year)
    month = random.randint(1, 12)
    return datetime(year, month, 1)

def fetch_google_cse_results(query, num_results=10):
    """Fetches search results from Google Custom Search JSON API."""
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        logging.error("GOOGLE_API_KEY or GOOGLE_CSE_ID environment variables not set. Please check your GitHub Secrets.")
        return []

    params = {
        "key": GOOGLE_API_KEY,
        "cx": GOOGLE_CSE_ID,
        "q": query,
        "num": num_results, # Max 10 per request for CSE API
    }
    
    try:
        logging.info(f"  Querying Google CSE for: '{query}'")
        response = requests.get(GOOGLE_CSE_API_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status() 
        data = response.json()
        
        articles = []
        if 'items' in data: # CSE API returns results in 'items'
            for result in data['items']:
                if 'link' in result and 'title' in result:
                    if not any(ext in result['link'].lower() for ext in ['.pdf', '.zip', '.exe', '.jpg', '.png', '.gif']):
                        articles.append({
                            "title": result['title'],
                            "link": result['link'],
                            "snippet": result.get('snippet', ''),
                            "source_domain": result.get('displayLink', '').replace('www.', '') # Use displayLink for domain
                        })
        return articles
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching Google CSE results: {e}")
        return []
    except json.JSONDecodeError as e:
        logging.error(f"JSON decode error from Google CSE response: {e}. Response: {response.text[:200]}...")
        return []

def process_image(image_url, article_id):
    """Downloads, resizes, compresses, and saves an image."""
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
    """Checks if the article title or text contains AI-related keywords."""
    title_lower = title.lower()
    text_lower = text.lower()
    for keyword in AI_KEYWORDS:
        if keyword in title_lower or keyword in text_lower:
            return True
    return False

def scrape_article(article_url, article_id, source_domain):
    """Scrapes a single article using newspaper3k and processes it."""
    try:
        config = newspaper.Config()
        config.browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        config.request_timeout = REQUEST_TIMEOUT

        article = newspaper.Article(article_url, config=config)
        article.download()
        article.parse()
        
        if not article.title or not article.text or len(article.text) < 100:
            logging.info(f"Skipping {article_url}: Missing title or too short content.")
            return None

        if not is_ai_relevant(article.title, article.text):
            logging.info(f"Skipping {article_url}: Not AI relevant after full content check.")
            return None

        summary = ' '.join(article.text.split()[:80])
        if len(article.text.split()) > 80:
            summary += '...'

        image_path = None
        if article.top_image:
            image_path = process_image(article.top_image, article_id)
        
        return {
            "id": article_id,
            "title": article.title,
            "summary": summary,
            "original_url": article_url,
            "wayback_url": None, # Not from Wayback Machine
            "image_path": image_path.replace("\\", "/") if image_path else None,
            "publish_date": article.publish_date.isoformat() if article.publish_date else datetime.now().isoformat(),
            "source": source_domain
        }
    except newspaper.article.ArticleException as e:
        logging.warning(f"Newspaper3k error processing {article_url}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        logging.warning(f"Request error fetching {article_url}: {e}")
        return None
    except Exception as e:
        logging.error(f"General error processing {article_url}: {e}")
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
    
    logging.info("Starting Google Custom Search API AI Time Capsule scraping run...")
    
    # Format for Month/Year name in query (e.g., "May 2003")
    month_names = ["January", "February", "March", "April", "May", "June", 
                   "July", "August", "September", "October", "November", "December"]

    while articles_added_this_run < MAX_ARTICLES_PER_RUN and attempts < MAX_SEARCH_ATTEMPTS:
        attempts += 1
        
        random_month_date = get_random_past_month(*PAST_YEAR_RANGE)
        
        # Create a query string that includes the month and year
        # This is how we achieve historical date filtering with CSE API
        target_month_year_str = f"{month_names[random_month_date.month - 1]} {random_month_date.year}"
        logging.info(f"Attempt {attempts}/{MAX_SEARCH_ATTEMPTS}: Searching for articles from: {target_month_year_str}")
        
        search_query = f"\"artificial intelligence\" news {target_month_year_str}"
        
        google_cse_results = fetch_google_cse_results(search_query, num_results=10) # Max 10 results per query for CSE
        
        if not google_cse_results:
            logging.info(f"  No relevant search results found for {target_month_year_str}.")
            time.sleep(2) 
            continue

        random.shuffle(google_cse_results) 
        
        for i, result in enumerate(google_cse_results):
            if articles_added_this_run >= MAX_ARTICLES_PER_RUN:
                break
            if result['link'] in existing_original_urls:
                logging.debug(f"  Skipping already processed: {result['link']}")
                continue
            
            potential_ai = False
            combined_text = (result['title'] + " " + result['snippet']).lower()
            if any(keyword in combined_text for keyword in AI_KEYWORDS):
                potential_ai = True

            if not potential_ai:
                logging.debug(f"  Skipping {result['link']}: No immediate AI keywords in title/snippet.")
                continue

            logging.info(f"  Attempting to scrape {i+1}/{len(google_cse_results)} potential AI articles: {result['link']}")
            article_id = f"{len(existing_articles) + articles_added_this_run}_{random.randint(1000,9999)}"
            
            article_data = scrape_article(result['link'], article_id, result['source_domain'])
            
            if article_data:
                existing_articles.append(article_data)
                existing_original_urls.add(result['link'])
                articles_added_this_run += 1
                logging.info(f"  SUCCESS: Added '{article_data['title']}' (Source: {article_data['source']})")
                if articles_added_this_run >= MAX_ARTICLES_PER_RUN:
                    break
            
            time.sleep(1.5) 

        time.sleep(3) 
        
    save_articles(existing_articles)
    logging.info(f"Finished run. Added {articles_added_this_run} new articles. Total articles in file: {len(existing_articles)}")

if __name__ == "__main__":
    main()
