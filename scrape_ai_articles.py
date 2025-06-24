# scrape_ai_articles.py (Eighth Revision: Journal & Academic Focus for Pre-2000 AI)
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
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") 
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")    
GOOGLE_CSE_API_URL = "https://www.googleapis.com/customsearch/v1"

# Expanded keywords to catch older terminology and academic context
AI_KEYWORDS = ["artificial intelligence", "ai", "machine learning", "deep learning", "neural network", 
               "robotics", "nlp", "computer vision", "AGI", "expert system", "neural computing", 
               "connectionism", "symbolic AI", "AI research", "AI program", 
               "computational intelligence", "cognitive science", "knowledge representation",
               "fuzzy logic", "genetic algorithms", "VR", "Cyber", "Cyberpunk"] # Added more
DATA_FILE = "ai_articles.json"
IMAGES_DIR = "images/ai_time_capsule"

MAX_ARTICLES_PER_RUN = 1  # Still aiming for 1 article per successful run, as results are sparse
MAX_SEARCH_ATTEMPTS = 200 # Increased attempts even further for very old content
REQUEST_TIMEOUT = 20      

# Targeting the desired older range: 1985-2000
PAST_YEAR_RANGE = (1985, 2000) 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

os.makedirs(IMAGES_DIR, exist_ok=True)

def get_random_past_month(start_year, end_year):
    year = random.randint(start_year, end_year)
    month = random.randint(1, 12)
    return datetime(year, month, 1)

def fetch_google_cse_results(query, num_results=10):
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        logging.error("GOOGLE_API_KEY or GOOGLE_CSE_ID environment variables not set. Please check your GitHub Secrets.")
        return []

    params = {
        "key": GOOGLE_API_KEY,
        "cx": GOOGLE_CSE_ID,
        "q": query,
        "num": num_results, 
    }
    
    try:
        logging.info(f"  Querying Google CSE for: '{query}'")
        response = requests.get(GOOGLE_CSE_API_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status() 
        data = response.json()
        
        articles = []
        if 'items' in data:
            for result in data['items']:
                if 'link' in result and 'title' in result:
                    # *** IMPORTANT CHANGE: Removed .pdf from exclusion list ***
                    # We will now attempt to scrape PDFs for academic papers.
                    if not any(ext in result['link'].lower() for ext in ['.zip', '.exe', '.jpg', '.png', '.gif', 'forum', 'forums', 'discussion', 'archive.org']):
                        articles.append({
                            "title": result['title'],
                            "link": result['link'],
                            "snippet": result.get('snippet', ''),
                            "source_domain": result.get('displayLink', '').replace('www.', '') 
                        })
        return articles
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching Google CSE results: {e}")
        return []
    except json.JSONDecodeError as e:
        logging.error(f"JSON decode error from Google CSE response: {e}. Response: {response.text[:200]}...")
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

def scrape_article(article_url, article_id, source_domain):
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
            "wayback_url": None, 
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
    
    month_names = ["January", "February", "March", "April", "May", "June", 
                   "July", "August", "September", "October", "November", "December"]

    while articles_added_this_run < MAX_ARTICLES_PER_RUN and attempts < MAX_SEARCH_ATTEMPTS:
        attempts += 1
        
        random_month_date = get_random_past_month(*PAST_YEAR_RANGE)
        
        target_month_year_str = f"{month_names[random_month_date.month - 1]} {random_month_date.year}"
        logging.info(f"Attempt {attempts}/{MAX_SEARCH_ATTEMPTS}: Searching for articles from: {target_month_year_str}")
        
        # *** AGGRESSIVELY TARGETED SEARCH QUERY FOR 1985-2000 ACADEMIC/JOURNAL CONTENT ***
        # Focused on journal sites and academic institutions identified as relevant.
        # Removed the OR logic for site: to simplify and make sure each domain is distinct
        # Added keywords specific to academic publications
        search_query = f'("artificial intelligence" OR "AI" OR "machine learning" OR "expert system" OR "neural computing" OR "connectionism" OR "symbolic AI" OR "cognitive science") {target_month_year_str} (site:aaai.org OR site:jair.org OR site:mit.edu OR site:stanford.edu OR site:ieee.org OR site:spectrum.ieee.org OR site:dl.acm.org OR site:acm.org OR site:sciencedirect.com OR site:onlinelibrary.wiley.com OR site:wired.com OR site:sciencedaily.com)'
        
        # Note: wired.com and sciencedaily.com have limited content before late 90s, but include for completeness.
        # You can manually test this query in Google.com to see what kind of results you get.
        
        google_cse_results = fetch_google_cse_results(search_query, num_results=10) 
        
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
            
            # Expanded filter if the link itself indicates non-article content
            if any(term in result['link'].lower() for term in ['forum', 'forums', 'discussion', 'comments', 'blog', 'index.html', '/tag/', '/category/', 'masthead', 'contact', 'about', 'member']):
                logging.debug(f"  Skipping {result['link']}: Appears to be a non-article page type.")
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
