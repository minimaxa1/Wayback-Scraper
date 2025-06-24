# generate_ai_analysis.py (Major Rebuild: Google CSE + Google Gemini for Synthesis)
import requests
import newspaper
import os
import json
import re
from PIL import Image
import io
import time
import random
from datetime import datetime, timedelta
import logging

# New import for Google Generative AI API
import google.generativeai as genai 

# --- Configuration ---
# Google CSE API
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")  # Your Google Cloud API Key
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")    # Your Custom Search Engine ID
GOOGLE_CSE_API_URL = "https://www.googleapis.com/customsearch/v1"

# Google Generative AI (Gemini) API
# Your GOOGLE_API_KEY is used here too, ensure Generative Language API is enabled.
GEMINI_MODEL = "gemini-pro" # Or "gemini-1.5-pro" for higher quality/cost if available and desired

# Data Storage
GENERATED_ARTICLES_DIR = "generated_articles"
IMAGES_DIR = "images/ai_time_capsule" # Keep this for header images
INDEX_FILE = "ai_analyses_index.json" # New index for generated articles

# Scraping & Search Parameters
AI_KEYWORDS = ["artificial intelligence", "ai", "machine learning", "deep learning", "neural network", 
               "robotics", "nlp", "computer vision", "AGI", "expert system", "neural computing", 
               "connectionism", "symbolic AI", "cognitive science", "knowledge representation",
               "fuzzy logic", "genetic algorithms", "AI system"] 
MAX_SCRAPED_ARTICLES_PER_RUN = 3 # Number of articles to attempt to scrape for synthesis
MAX_SEARCH_ATTEMPTS_PER_RUN = 150 # How many search queries to make before giving up on a batch
REQUEST_TIMEOUT = 20      

# Historical Date Range
PAST_YEAR_RANGE = (1985, 2000) 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

os.makedirs(GENERATED_ARTICLES_DIR, exist_ok=True)
os.makedirs(IMAGES_DIR, exist_ok=True)

# --- Google Gemini Client Setup ---
# The GOOGLE_API_KEY needs to be set as an environment variable for genai.configure()
# This is handled by GitHub Actions env: in the YAML
if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        logging.info("Google Gemini API client configured.")
    except Exception as e:
        logging.error(f"Failed to configure Google Gemini client: {e}")
else:
    logging.warning("GOOGLE_API_KEY not set. LLM synthesis will not work.")

# --- Utility Functions ---

def get_random_past_month(start_year, end_year):
    year = random.randint(start_year, end_year)
    month = random.randint(1, 12)
    return datetime(year, month, 1)

def fetch_google_cse_results(query, num_results=10):
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        logging.error("GOOGLE_API_KEY or GOOGLE_CSE_ID environment variables not set.")
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
        
        results = []
        if 'items' in data:
            for item in data['items']:
                if 'link' in item and 'title' in item:
                    if not any(ext in item['link'].lower() for ext in ['.zip', '.exe', '.jpg', '.png', '.gif', 'forum', 'forums', 'discussion', 'archive.org', 'support.google.com']):
                        results.append({
                            "title": item['title'],
                            "link": item['link'],
                            "snippet": item.get('snippet', ''),
                            "source_domain": item.get('displayLink', '').replace('www.', '') 
                        })
        return results
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching Google CSE results: {e}")
        return []
    except json.JSONDecodeError as e:
        logging.error(f"JSON decode error from Google CSE response: {e}. Response: {response.text[:200]}...")
        return []

def process_image(article_id): # No longer needs image_url from scrape_article
    """Generates a random image URL from Unsplash for the generated article header."""
    try:
        # Using a random query for a placeholder image to match the template's style.
        random_unsplash_url = f"https://source.unsplash.com/random/1080x720?technology,abstract,futuristic,circuit,neural&sig={random.randint(1,1000000)}"
        return random_unsplash_url
    except Exception as e:
        logging.warning(f"Could not get random Unsplash image: {e}")
        # Fallback to a static placeholder image from user's template
        return "https://images.unsplash.com/photo-1445160307478-288488e5da27?crop=entropy&cs=tinysrgb&fit=max&fm-jpg&ixid=M3w3NjUwNzN8MHwxfHJhbmRvbXx8fHx8fHx8fDE3NTA2ODE1NzB8&ixlib=rb-4.1.0&q=80&w=1080" 

def is_ai_relevant(title, text):
    title_lower = title.lower()
    text_lower = text.lower()
    for keyword in AI_KEYWORDS:
        if keyword in title_lower or keyword in text_lower:
            return True
    return False

def scrape_full_article_text(article_url):
    """Scrapes the full text of an article using newspaper3k."""
    try:
        config = newspaper.Config()
        config.browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        config.request_timeout = REQUEST_TIMEOUT
        config.fetch_images = False # Not needed for LLM synthesis, we use a separate header image
        config.MAX_FILE_MEM_KB = 5000 # Increase if large PDFs are failing, default is 500kb
        config.browser = "chrome" # Try to ensure better compatibility

        article = newspaper.Article(article_url, config=config)
        article.download()
        article.parse()
        
        if not article.title or not article.text or len(article.text) < 200: # Need substantial text for synthesis
            logging.info(f"Skipping {article_url}: Missing title or too short content for synthesis (len {len(article.text) if article.text else 0}).")
            return None

        if not is_ai_relevant(article.title, article.text):
            logging.info(f"Skipping {article_url}: Not AI relevant after full content check for synthesis.")
            return None
        
        return {
            "title": article.title,
            "text": article.text,
            "url": article_url,
            "publish_date": article.publish_date.isoformat() if article.publish_date else "Unknown",
            "source": article.source_url 
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

def generate_ai_analysis(scraped_articles, target_month_year_str):
    """Uses Google Gemini API to synthesize an article based on scraped content."""
    if not GOOGLE_API_KEY: # Check if API key is even available
        logging.error("Google Gemini client not configured. Cannot generate analysis.")
        return None

    if not scraped_articles:
        logging.warning("No articles provided for AI analysis.")
        return None

    combined_content = ""
    for i, article in enumerate(scraped_articles):
        combined_content += f"--- Article {i+1} (Source: {article.get('source', 'Unknown')}, URL: {article['url']}, Date: {article['publish_date']}) ---\n"
        combined_content += f"Title: {article['title']}\n"
        # Limit text sent to LLM for token/cost reasons
        combined_content += f"Content: {article['text'][:2000]}...\n\n" 
    
    # Craft the prompt for Gemini, emphasizing HTML structure and content goals
    # The prompt is critical for getting the desired output style and analysis.
    prompt_template = f"""
    You are an insightful public intellectual with a deep understanding of technology and its societal impact, writing in the style of the 'Architecting You' blog. Your task is to analyze historical discussions around Artificial Intelligence from the era of {target_month_year_str} based on the provided articles.

    Synthesize these articles into a new, compelling article that offers a "look from the past with a review of what they got right from a prescient viewpoint." Build this into an interesting, cohesive piece of content.

    **Focus your analysis on:**
    - Key themes, predictions, and prevailing sentiments about AI during {target_month_year_str} found in the articles.
    - What aspects of their thinking, discussions, or predictions turned out to be strikingly prescient (accurate and forward-looking) from a modern (2024) perspective.
    - How their understanding of AI's implications relates to our current digital environment, highlighting any surprising similarities or overlooked aspects.
    - Incorporate direct or paraphrased insights from the provided source articles, citing them by source (e.g., from [Source Domain]) when appropriate.

    **Structure your response STRICTLY using HTML tags to fit the following format, emulating the dark, minimalist, and analytical style of 'The Unseen Edifice' article. Do NOT include `<html>`, `<head>`, `<body>` tags or `header`, `main`, `footer` wrappers for the entire document. Provide ONLY the content that would go *inside* the `div class="content-panel"` element, including the `<p class="hook">` at the start.**

    **Required HTML Structure and Elements:**
    - Start with ONE `<p class="hook">` paragraph for the opening hook.
    - Use multiple standard paragraphs (`<p>`).
    - Include at least one blockquote (`<blockquote>`) for a prominent past insight.
    - Include at least one `<h3>` for a sub-section title (e.g., "Prescient Insights from the Past", "Early Concerns and Modern Echoes").
    - Include at least one ordered list (`<ol>`) with `<li>` items for "Key Takeaways" or "Lessons Learned."
    - Use `<span class="highlight">` around key phrases or particularly prescient insights.
    - Use `<hr class="section-divider">` between major sections to break up the text.
    - **Ensure all generated text is wrapped correctly within these HTML tags.**

    **Combined Content from Scraped Articles (Analyze these):**
    {combined_content}

    **Your Synthesized Article (HTML formatted, directly insertable into the content-panel div):**
    """
    
    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(
            prompt_template,
            generation_config=genai.types.GenerationConfig(
                candidate_count=1,
                stop_sequences=None,
                max_output_tokens=2000, # Max length of the generated response
                temperature=0.7, # Controls creativity (0.0 for factual, 1.0 for creative)
                top_p=1,
                top_k=1,
            ),
        )
        # Access the text from the response
        generated_text = response.candidates[0].content.parts[0].text
        logging.info("Successfully generated analysis using Google Gemini API.")
        return generated_text
    except Exception as e:
        logging.error(f"Error generating AI analysis with Google Gemini: {e}")
        if hasattr(e, 'response') and hasattr(e.response, 'text'):
            logging.error(f"Gemini API error response: {e.response.text}")
        return None


def create_full_html_article(generated_content, primary_scrape_date_str, image_url):
    """Inserts generated content into the full HTML template and extracts dynamic parts."""
    
    # Attempt to extract <h1> content and <p class="hook"> content from generated_content
    # This makes the main title and hook dynamic based on LLM output.
    
    # Default values if extraction fails or LLM doesn't follow instructions perfectly
    generated_title = f"Integrative Analysis of AI in {primary_scrape_date_str}"
    generated_hook = "A look back at the early days of AI through a modern lens."
    main_article_body_html = generated_content 
    
    # Regex to find <h1>...</h1> but make it non-greedy with ? and DOTALL to span lines
    match_h1 = re.search(r'<h1>(.*?)<\/h1>', generated_content, re.IGNORECASE | re.DOTALL)
    if match_h1:
        generated_title = match_h1.group(1).strip()
        # Remove the extracted h1 from the content body
        main_article_body_html = re.sub(r'<h1>.*?<\/h1>', '', main_article_body_html, flags=re.IGNORECASE | re.DOTALL, count=1).strip()

    # Regex to find <p class="hook">...</p>
    match_hook = re.search(r'<p\s+class="hook">(.*?)<\/p>', main_article_body_html, re.IGNORECASE | re.DOTALL)
    if match_hook:
        generated_hook = match_hook.group(1).strip()
        # Remove the extracted hook from the content body
        main_article_body_html = re.sub(r'<p\s+class="hook">.*?<\/p>', '', main_article_body_html, flags=re.IGNORECASE | re.DOTALL, count=1).strip()

    
    html_template = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{generated_title} - Architecting You</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,700;1,400&family=Source+Code+Pro:wght@400;700&display=swap" rel="stylesheet">
<style>:root{{--grid-color:rgba(200,200,200,0.1);--text-color:#E0E0E0;--bg-color:#111;--panel-bg-color:rgba(18,18,18,0.9);--panel-border-color:#444;--highlight-color:#00BFFF;--quote-border-color:#4A90E2}}body{{font-family:'Lora',serif;line-height:1.8;color:var(--text-color);background-color:var(--bg-color);background-image:linear-gradient(var(--grid-color) 1px,transparent 1px),linear-gradient(90deg,var(--grid-color) 1px,transparent 1px);background-size:40px 40px;margin:0;padding:2rem}}.main-container{{max-width:800px;margin:2rem auto}}.main-header{{text-align:center;margin-bottom:2rem}}h1{{font-family:'Source Code Pro',monospace;font-size:2.8rem;font-weight:700;color:#FFF;text-transform:uppercase;letter-spacing:.3em;word-spacing:.5em;margin:0;padding-left:.3em}}.main-header p{{font-family:'Source Code Pro',monospace;font-size:.9rem;text-transform:uppercase;letter-spacing:.2em;color:#FFF;margin-top:1rem}}.article-image{{width:100%;height:auto;margin-bottom:2rem;border:1px solid var(--panel-border-color)}}.content-panel{{background-color:var(--panel-bg-color);border:1px solid var(--panel-border-color);padding:2.5rem;backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px)}}.content-panel p,.content-panel li{{font-size:1.1rem}}.content-panel .hook{{font-size:1.3rem;line-height:1.7;font-style:italic;color:#BDBDBD;margin-bottom:2rem}}.content-panel h3{{font-family:'Source Code Pro',monospace;font-size:1.5rem;margin-top:2.5rem;color:#FFF}}.content-panel blockquote{{font-family:'Lora',serif;font-size:1.4rem;font-style:italic;font-weight:700;border-left:4px solid var(--quote-border-color);padding-left:1.5rem;margin:2.5rem 0;color:#A7C7E7}}.content-panel .highlight{{background-color:rgba(0,191,255,0.15);padding:.1rem .3rem}}.content-panel .section-divider{{border:0;height:1px;background-color:#444;margin:3rem 0}}.cta-container{{background-color:var(--panel-bg-color);border:1px solid var(--panel-border-color);backdrop-filter:blur(8px);margin-top:2rem;text-align:center}}.cta-container .panel-title-bar{{background-color:var(--panel-border-color);color:#FFF;padding:.5rem 1rem;font-family:'Source Code Pro',monospace;font-weight:700;text-transform:uppercase;letter-spacing:.1em}}.cta-container .panel-body{{padding:1.5rem}}.button-container{{display:flex;justify-content:center;gap:1.5rem;margin-top:2rem;flex-wrap:wrap}}.action-button{{font-family:'Source Code Pro',monospace;font-weight:700;text-transform:uppercase;letter-spacing:.1em;background-color:transparent;color:var(--highlight-color);border:2px solid var(--highlight-color);padding:.7rem 1.2rem;font-size:.9rem;text-decoration:none;transition:background-color .2s,color .2s}.action-button:hover{{background-color:var(--highlight-color);color:var(--bg-color)}}</style></head>
<body>
<div class="main-container">
    <header class="main-header">
        <h1>{generated_title}</h1>
        <p>A Historical AI Insight from {primary_scrape_date_str}</p>
    </header>
    <main class="content-wrapper">
        <img src="{image_url}" alt="AI themed abstract image" class="article-image">
        <div class="content-panel">
            {main_article_body_html}
        </div>
        <div class="cta-container">
            <div class="panel-title-bar">Dive Deeper</div>
            <div class="panel-body">
                <p>This analysis is part of the ongoing 'Architecting You' project. Explore more insights into technology, design, and your digital future.</p>
                <a href="https://www.amazon.com/Architecting-You-Bohemai-Art-ebook/dp/B0F9WDHYSL/" class="action-button" target="_blank">[ View on Amazon ]</a>
            </div>
        </div>
        <div class="button-container">
            <a href="index.html" class="action-button">[ Back to Home ]</a>
            <a href="ai-time-capsule.html" class="action-button">[ Back to AI Time Capsule Index ]</a>
        </div>
    </main>
</div>
</body>
</html>
    """
    return html_template

def load_existing_index():
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                logging.warning(f"Corrupt or empty {INDEX_FILE}, starting fresh.")
                return []
    return []

def save_index(index_data):
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(index_data, f, indent=2, ensure_ascii=False)

def main():
    generated_analyses_index = load_existing_index()
    
    analyses_added_this_run = 0
    attempts = 0
    
    logging.info("Starting Google CSE + Google Gemini AI Time Capsule Generation run...")
    
    month_names = ["January", "February", "March", "April", "May", "June", 
                   "July", "August", "September", "October", "November", "December"]

    # We aim to generate 1 analysis article per run
    while analyses_added_this_run < 1 and attempts < MAX_SEARCH_ATTEMPTS_PER_RUN: 
        attempts += 1
        
        random_month_date = get_random_past_month(*PAST_YEAR_RANGE)
        primary_scrape_date_str = f"{month_names[random_month_date.month - 1]} {random_month_date.year}"
        logging.info(f"Attempt {attempts}/{MAX_SEARCH_ATTEMPTS_PER_RUN}: Searching for raw articles from: {primary_scrape_date_str}")
        
        # Aggressively targeted search query for 1985-2000 academic/journal content
        search_query = f'("artificial intelligence" OR "AI" OR "machine learning" OR "expert system" OR "neural computing" OR "connectionism" OR "symbolic AI" OR "cognitive science") {primary_scrape_date_str} (site:aaai.org OR site:jair.org OR site:mit.edu OR site:stanford.edu OR site:ieee.org OR site:spectrum.ieee.org OR site:dl.acm.org OR site:acm.org OR site:sciencedirect.com OR site:onlinelibrary.wiley.com OR site:wired.com OR site:sciencedaily.com)'
        
        google_cse_results = fetch_google_cse_results(search_query, num_results=10) 
        
        if not google_cse_results:
            logging.info(f"  No relevant search results found in Google CSE for {primary_scrape_date_str}. Trying next date.")
            time.sleep(2) 
            continue

        random.shuffle(google_cse_results) 
        
        scraped_articles_for_synthesis = []
        # Try to scrape up to MAX_SCRAPED_ARTICLES_PER_RUN articles
        for i, result in enumerate(google_cse_results):
            if len(scraped_articles_for_synthesis) >= MAX_SCRAPED_ARTICLES_PER_RUN:
                break
            
            # Simple check if the link itself indicates non-article content
            if any(term in result['link'].lower() for term in ['forum', 'forums', 'discussion', 'comments', 'blog', 'index.html', '/tag/', '/category/', 'masthead', 'contact', 'about', 'member']):
                logging.debug(f"  Skipping {result['link']}: Appears to be a non-article page type.")
                continue

            potential_ai = False
            combined_text_from_search = (result['title'] + " " + result['snippet']).lower()
            if any(keyword in combined_text_from_search for keyword in AI_KEYWORDS):
                potential_ai = True

            if not potential_ai:
                logging.debug(f"  Skipping {result['link']}: No immediate AI keywords in title/snippet.")
                continue

            logging.info(f"  Attempting to scrape raw text from potential AI article: {result['link']}")
            article_content = scrape_full_article_text(result['link'])
            
            if article_content:
                scraped_articles_for_synthesis.append(article_content)
                logging.info(f"  Successfully scraped raw text from '{article_content['title']}'.")
            
            time.sleep(1.5) # Pause between scraping target articles

        if not scraped_articles_for_synthesis:
            logging.info(f"  No suitable articles scraped for synthesis from {primary_scrape_date_str}. Trying next date.")
            time.sleep(3) # Pause before trying next random date
            continue

        # --- LLM Synthesis Step ---
        logging.info(f"  Proceeding to generate AI analysis using Gemini for {len(scraped_articles_for_synthesis)} articles.")
        generated_html_content = generate_ai_analysis(scraped_articles_for_synthesis, primary_scrape_date_str)

        if generated_html_content:
            # Generate a unique filename for the new article
            timestamp_slug = datetime.now().strftime("%Y%m%d%H%M%S")
            filename = f"ai_analysis_{timestamp_slug}.html"
            html_path = os.path.join(GENERATED_ARTICLES_DIR, filename)
            
            # Get a random image URL for the article header
            header_image_url = process_image(filename) # Pass filename for unique sig

            full_article_html = create_full_html_article(
                generated_html_content,
                f"AI in the Era of {primary_scrape_date_str}", # Default title prefix
                primary_scrape_date_str,
                header_image_url
            )
            
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(full_article_html)
            
            # Add to index for frontend display
            analysis_data = {
                "id": f"analysis_{timestamp_slug}",
                "title": f"AI in the Era of {primary_scrape_date_str}", # This will be updated later by JS if LLM provides h1
                "summary": "An insightful look back at historical AI concepts and their prescience.", # This will be updated later by JS if LLM provides hook
                "html_path": html_path.replace("\\", "/"), # For web path consistency
                "generated_date": datetime.now().isoformat(),
                "original_sources_count": len(scraped_articles_for_synthesis),
                "featured_image": header_image_url
            }
            # Attempt to extract title and summary from the generated_html_content for the index
            match_h1_for_index = re.search(r'<h1>(.*?)<\/h1>', generated_html_content, re.IGNORECASE | re.DOTALL)
            if match_h1_for_index:
                analysis_data['title'] = match_h1_for_index.group(1).strip()
            
            match_hook_for_index = re.search(r'<p\s+class="hook">(.*?)<\/p>', generated_html_content, re.IGNORECASE | re.DOTALL)
            if match_hook_for_index:
                analysis_data['summary'] = match_hook_for_index.group(1).strip()
            
            generated_analyses_index.append(analysis_data)
            analyses_added_this_run += 1
            logging.info(f"  SUCCESS: Generated new analysis article: {filename}")
        else:
            logging.warning("  Failed to generate analysis content for this attempt.")
        
        time.sleep(5) # Longer pause after a full attempt cycle (search + scrape + generate)

    save_index(generated_analyses_index)
    logging.info(f"Finished run. Added {analyses_added_this_run} new analysis articles. Total analyses in index: {len(generated_analyses_index)}")

if __name__ == "__main__":
    main()
