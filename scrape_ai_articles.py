# generate_ai_analysis.py (Final/Most Intelligent Revision: Google CSE + Gemini for Deep Synthesis)
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
GEMINI_MODEL = "gemini-pro" # Consider "gemini-1.5-pro" for higher quality/cost if available and desired
# Ensure Generative Language API is enabled in your Google Cloud project for your API_KEY

# Data Storage
GENERATED_ARTICLES_DIR = "generated_articles"
IMAGES_DIR = "images/ai_time_capsule" # This folder is for the main generated article's header image
INDEX_FILE = "ai_analyses_index.json" # Index for generated articles

# Scraping & Search Parameters
AI_KEYWORDS = ["artificial intelligence", "ai", "machine learning", "deep learning", "neural network", 
               "robotics", "nlp", "computer vision", "AGI", "expert system", "neural computing", 
               "connectionism", "symbolic AI", "cognitive science", "knowledge representation",
               "fuzzy logic", "genetic algorithms", "AI system", "cybernetics", "automaton",
               "pattern recognition", "human-computer interaction", "AI winter"] # Added more
# Broader terms for search query specific to academic/publication types
PUBLICATION_KEYWORDS = ["paper", "proceedings", "journal", "report", "technical report", "conference", "symposium", "magazine"]

MAX_SCRAPED_ARTICLES_FOR_SYNTHESIS = 3 # Number of articles to attempt to scrape for synthesis input to LLM (adjust based on LLM context window)
MAX_SEARCH_ATTEMPTS_PER_RUN = 200 # Max attempts to find a suitable random month/year with results
REQUEST_TIMEOUT = 25      # Timeout for network requests (slightly adjusted)

# Historical Date Range
PAST_YEAR_RANGE = (1985, 2000) 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

os.makedirs(GENERATED_ARTICLES_DIR, exist_ok=True)
os.makedirs(IMAGES_DIR, exist_ok=True) # Ensure this exists for potential local image use (though we use Unsplash now)

# --- Google Gemini Client Setup ---
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
                    # Allow PDFs and common document types, but filter clear non-articles
                    if not any(ext in item['link'].lower() for ext in ['.zip', '.exe', '.jpg', '.png', '.gif', 'forum', 'forums', 'discussion', 'archive.org', 'support.google.com', 'jobs.google.com', 'developers.google.com']):
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

def get_header_image_url(article_id):
    """Generates a random image URL from Unsplash for the generated article header."""
    try:
        # Using a random query for a placeholder image to match the template's style.
        # Added more relevant keywords for AI/tech visuals.
        random_unsplash_url = f"https://source.unsplash.com/random/1080x720?technology,abstract,futuristic,circuit,neural,network,data,ai&sig={random.randint(1,1000000)}"
        return random_unsplash_url
    except Exception as e:
        logging.warning(f"Could not get random Unsplash image: {e}")
        # Fallback to a static placeholder image from user's template
        return "https://images.unsplash.com/photo-1445160307478-288488e5da27?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w3NjUwNzN8MHwxfHJhbmRvbXx8fHx8fHx8fDE3NTA2ODE1NzB8&ixlib=rb-4.1.0&q=80&w=1080" 

def is_ai_relevant(title, text):
    """Checks if the article title or text contains AI-related keywords."""
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
        config.fetch_images = False 
        config.MAX_FILE_MEM_KB = 5000 
        config.browser = "chrome" 
        config.memoize_articles = False # Ensure fresh download each time if debugging locally

        article = newspaper.Article(article_url, config=config)
        article.download()
        article.parse()
        
        if not article.title or not article.text or len(article.text) < 250: # Increased minimum text length for synthesis quality
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

def generate_ai_analysis(scraped_articles, historical_date_str):
    """Uses Google Gemini API to synthesize an article based on scraped content."""
    if not GOOGLE_API_KEY: 
        logging.error("Google Gemini client not configured. Cannot generate analysis.")
        return None

    if not scraped_articles:
        logging.warning("No articles provided for AI analysis.")
        return None

    combined_content = ""
    for i, article in enumerate(scraped_articles):
        # Provide source information prominently for LLM to integrate
        combined_content += f"--- Source Article {i+1} ---\n"
        combined_content += f"Title: {article['title']}\n"
        combined_content += f"URL: {article['url']}\n"
        combined_content += f"Published Date (as scraped): {article['publish_date']}\n"
        combined_content += f"Source Domain: {article['source']}\n"
        # Limit text sent to LLM for token/cost reasons, but ensure enough context
        # Aim for 1500-2000 tokens per article for Gemini-pro, adjust as needed.
        # This will vary per article. Sum of text should fit prompt context window.
        combined_content += f"Content Excerpt:\n{article['text'][:3000]}...\n\n" 
    
    # --- The "Prompt Intel" ---
    # This prompt is meticulously designed to elicit the desired output,
    # emulating the analytical and insightful style of your blog.
    prompt_template = f"""
    You are an **AI News Detective** and a **Public Intellectual** for the 'Architecting You' blog (https://minimaxa1.github.io/Architecting-You/). Your mission is to delve into historical technology discussions, specifically around Artificial Intelligence from the era of **{historical_date_str}**, based on the provided articles.

    **Your core task is to synthesize these historical texts into a novel, deeply insightful new article.** This article should offer a compelling "look from the past" by analyzing what they got right (their prescient viewpoints) and what they couldn't foresee, building a bridge to our current understanding of AI.

    **Adopt the analytical, philosophical, and empowering tone of 'Architecting You'.** Focus on defining and dissecting the 'unseen edifice' of our digital environment, connecting past ideas to current AI technology and its societal implications.

    **Key Analytical Tasks & Content Requirements:**
    1.  **Historical Core:** Extract the dominant ideas, prevailing paradigms (e.g., expert systems, symbolic AI, neural networks in that era), major challenges, and key debates surrounding AI during {historical_date_str}. What were the **hopes, fears, and conceptual frameworks** guiding AI research and public perception then?
    2.  **Prescient Foresight:** Identify **specific, striking predictions or insights** from these historical articles that proved remarkably accurate or deeply foundational when viewed through the lens of **current AI technology (2024)**. Think about:
        *   The rise of specific AI subfields (e.g., machine learning, neural nets if discussed).
        *   The nature of human-AI interaction.
        *   Societal impacts, ethical concerns, or philosophical questions that resonate today (e.g., autonomy, data, algorithmic influence, consciousness, trust).
        *   The importance of data, computational power, or specific architectural designs.
        *   Use `<span class="highlight">` for these particularly prescient insights.
    3.  **Blind Spots & Unforeseen Trajectories:** What significant advancements, challenges, or societal shifts in AI (from our 2024 perspective, e.g., large language models, deep learning's scale, generative AI, sophisticated reinforcement learning, ubiquitous AI integration) did they largely **miss, underestimate, or simply not conceptualize**? Why might this have been the case given their context?
    4.  **Novel Understanding/Synthesis ("Old into New"):** How does juxtaposing these past views with our current reality forge a *new, fascinating understanding* of AI's trajectory? What does this historical reflection teach us about the evolution of technology, the nature of innovation, or our ongoing relationship with the 'unseen edifice'? Frame this as insights for navigating complexity.
    5.  **Attribution:** Naturally weave in references to the source articles within your analysis (e.g., "A seminal paper from [Source Domain] in [Year] highlighted...", "As discussed on [Source Domain]'s pages...").

    **Strict HTML Structure and Styling (Crucial):**
    Your output MUST be a direct, parseable HTML snippet ready to be inserted into the `<div class="content-panel">` element of the blog's HTML template. **Do NOT include `<html>`, `<head>`, `<body>` tags or full document wrappers.**

    **Required Elements:**
    - Start with **ONE** thought-provoking `<p class="hook">` paragraph (this will be extracted for the index and prominently displayed).
    - Use multiple standard paragraphs (`<p>`).
    - Include at least **ONE** `<blockquote>` for a prominent past insight or quote.
    - Include at least **TWO** `<h3>` for distinct sub-sections (e.g., "The Echoes of Foresight", "Unseen Paths: What They Couldn't Know").
    - Include at least **ONE** ordered list (`<ol>`) with `<li>` items for "Key Takeaways," "Lessons Learned," or "Actionable Insights for Navigating the Future."
    - Use `<span class="highlight">` around key phrases or particularly prescient insights, as seen in the 'Unseen Edifice' example.
    - Use `<hr class="section-divider">` between major sections to provide visual breaks.

    **Combined Content from Scraped Articles (Analyze these sources):**
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
                max_output_tokens=2500, # Increased max output tokens for longer, richer articles
                temperature=0.8, # Slightly increased for more creativity in synthesis
                top_p=0.95,
                top_k=40,
            ),
        )
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
    
    # Attempt to extract dynamic content based on LLM's expected output structure
    generated_title = f"AI in the Era of {primary_scrape_date_str}"
    generated_hook = "An insightful look back at historical AI concepts and their prescience."
    main_article_body_html = generated_content 
    
    # Regex to find <h1>...</h1> (non-greedy, DOTALL for multiline)
    match_h1 = re.search(r'<h1>(.*?)<\/h1>', generated_content, re.IGNORECASE | re.DOTALL)
    if match_h1:
        generated_title = match_h1.group(1).strip()
        main_article_body_html = re.sub(r'<h1>.*?<\/h1>', '', main_article_body_html, flags=re.IGNORECASE | re.DOTALL, count=1).strip()

    # Regex to find <p class="hook">...</p>
    match_hook = re.search(r'<p\s+class="hook">(.*?)<\/p>', main_article_body_html, re.IGNORECASE | re.DOTALL)
    if match_hook:
        generated_hook = match_hook.group(1).strip()
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
        
        # *** AGGRESSIVELY TARGETED SEARCH QUERY FOR 1985-2000 ACADEMIC/JOURNAL CONTENT ***
        # Increased number of keywords and focused on academic/journal sites.
        ai_search_terms = " OR ".join(f'"{kw}"' for kw in AI_KEYWORDS) # Format keywords for OR search
        publication_search_terms = " OR ".join(f'"{kw}"' for kw in PUBLICATION_KEYWORDS) # Format publication keywords for OR search

        # Domains identified as relevant for academic/journal content from your finds
        targeted_domains = [
            "aaai.org", "jair.org", "mit.edu", "stanford.edu", "cmu.edu", "berkeley.edu", # Universities & AI Societies
            "ieee.org", "spectrum.ieee.org", "acm.org", "dl.acm.org",                     # Professional Societies / Digital Libraries
            "sciencedirect.com", "onlinelibrary.wiley.com",                              # Major Publishers (might be paywalled)
            "wired.com", "sciencedaily.com",                                              # Late 90s Tech News
            "ijcai.org", "nips.cc", "icml.cc"                                             # Conference sites (for proceedings)
        ]
        site_operators = " OR ".join(f"site:{d}" for d in targeted_domains)

        # Combine everything into the final query
        search_query = f'({ai_search_terms}) ({publication_search_terms}) {primary_scrape_date_str} ({site_operators})'
        
        # Example: ("artificial intelligence" OR "AI") (paper OR journal) May 1990 (site:mit.edu OR site:aaai.org)
        logging.debug(f"  Generated search query: {search_query}")
        
        google_cse_results = fetch_google_cse_results(search_query, num_results=10) 
        
        if not google_cse_results:
            logging.info(f"  No relevant search results found in Google CSE for {primary_scrape_date_str} with current query. Trying next date.")
            time.sleep(2) 
            continue

        random.shuffle(google_cse_results) 
        
        scraped_articles_for_synthesis = []
        # Try to scrape up to MAX_SCRAPED_ARTICLES_FOR_SYNTHESIS articles
        for i, result in enumerate(google_cse_results):
            if len(scraped_articles_for_synthesis) >= MAX_SCRAPED_ARTICLES_FOR_SYNTHESIS:
                break
            
            # Additional pre-filter if the link itself indicates non-article/paper content
            if any(term in result['link'].lower() for term in ['forum', 'forums', 'discussion', 'comments', 'blog', 'index.html', '/tag/', '/category/', 'masthead', 'contact', 'about', 'member', 'privacy', 'legal', 'jobs', 'careers', '.css', '.js', '.xml', 'robots.txt']):
                logging.debug(f"  Skipping {result['link']}: Appears to be a non-article page type.")
                continue

            # Ensure AI keywords are strongly present in title/snippet before attempting full scrape
            potential_ai = False
            combined_text_from_search = (result['title'] + " " + result['snippet']).lower()
            if any(keyword in combined_text_from_search for keyword in AI_KEYWORDS):
                potential_ai = True

            if not potential_ai:
                logging.debug(f"  Skipping {result['link']}: No strong AI keywords in title/snippet.")
                continue

            logging.info(f"  Attempting to scrape raw text from potential AI article: {result['link']}")
            article_content = scrape_full_article_text(result['link'])
            
            if article_content:
                scraped_articles_for_synthesis.append(article_content)
                logging.info(f"  Successfully scraped raw text from '{article_content['title']}'. Scraped count: {len(scraped_articles_for_synthesis)}")
            
            time.sleep(1.5) # Pause between scraping individual target articles

        if not scraped_articles_for_synthesis:
            logging.info(f"  No suitable articles scraped for synthesis from {primary_scrape_date_str} after full scraping attempts. Trying next date.")
            time.sleep(3) # Pause before trying next random date
            continue

        # --- LLM Synthesis Step ---
        logging.info(f"  Proceeding to generate AI analysis using Gemini for {len(scraped_articles_for_synthesis)} scraped articles from {primary_scrape_date_str}.")
        generated_html_content = generate_ai_analysis(scraped_articles_for_synthesis, primary_scrape_date_str)

        if generated_html_content:
            # Generate a unique filename for the new article
            timestamp_slug = datetime.now().strftime("%Y%m%d%H%M%S")
            filename = f"ai_analysis_{timestamp_slug}.html"
            html_path = os.path.join(GENERATED_ARTICLES_DIR, filename)
            
            # Get a random image URL for the article header
            header_image_url = get_header_image_url(filename) 

            # Create the full HTML file
            full_article_html = create_full_html_article(
                generated_html_content,
                primary_scrape_date_str, # Date string for header
                header_image_url
            )
            
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(full_article_html)
            
            # Add to index for frontend display
            analysis_data = {
                "id": f"analysis_{timestamp_slug}",
                "title": f"AI in the Era of {primary_scrape_date_str}", 
                "summary": "An insightful look back at historical AI concepts and their prescience.", 
                "html_path": html_path.replace("\\", "/"), # For web path consistency
                "generated_date": datetime.now().isoformat(),
                "original_sources_count": len(scraped_articles_for_synthesis),
                "featured_image": header_image_url
            }
            # Attempt to extract title and summary from the generated_html_content for the index
            # This relies on the LLM generating the hook and h1 as requested in the prompt
            match_h1_for_index = re.search(r'<h1[^>]*>(.*?)<\/h1>', generated_html_content, re.IGNORECASE | re.DOTALL)
            if match_h1_for_index:
                analysis_data['title'] = match_h1_for_index.group(1).strip()
            
            match_hook_for_index = re.search(r'<p\s+class="hook"[^>]*>(.*?)<\/p>', generated_html_content, re.IGNORECASE | re.DOTALL)
            if match_hook_for_index:
                analysis_data['summary'] = match_hook_for_index.group(1).strip()
            
            generated_analyses_index.append(analysis_data)
            analyses_added_this_run += 1
            logging.info(f"  SUCCESS: Generated new analysis article: {filename}")
        else:
            logging.warning("  Failed to generate analysis content for this attempt with Gemini.")
        
        time.sleep(5) # Longer pause after a full attempt cycle (search + scrape + generate)

    save_index(generated_analyses_index)
    logging.info(f"Finished run. Added {analyses_added_this_run} new analysis articles. Total analyses in index: {len(generated_analyses_index)}")

if __name__ == "__main__":
    main()
