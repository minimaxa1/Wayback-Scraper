# generate_ai_analysis.py (Final, FINAL, Corrected `ai_search_terms` line)

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

import google.generativeai as genai 

# --- Configuration ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")  
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")    
GOOGLE_CSE_API_URL = "https://www.googleapis.com/customsearch/v1"

# --- IMPORTANT: Changed GEMINI_MODEL to 'gemini-1.0-flash' as requested ---
GEMINI_MODEL = "gemini-1.5-flash" 

GENERATED_ARTICLES_DIR = "generated_articles"
IMAGES_DIR = "images/ai_time_capsule" 
INDEX_FILE = "ai_analyses_index.json" 

AI_KEYWORDS = ["artificial intelligence", "ai", "machine learning", "deep learning", "neural network", 
               "robotics", "nlp", "computer vision", "AGI", "expert system", "neural computing", 
               "connectionism", "symbolic AI", "cognitive science", "knowledge representation",
               "fuzzy logic", "genetic algorithms", "AI system", "cybernetics", "automaton",
               "pattern recognition", "human-computer interaction", "AI winter", "inference engine",
               "data mining", "predictive analytics", "cyberpunk", "AI expert", "robot", "intelligent agent",
               "knowledge-based system", "computational linguistics"] 

PUBLICATION_KEYWORDS = ["paper", "proceedings", "journal", "report", "technical report", "conference", "symposium", "magazine", "article", "thesis", "dissertation"] 

MAX_SCRAPED_ARTICLES_FOR_SYNTHESIS = 1 
MAX_SEARCH_ATTEMPTS_PER_RUN = 100 
REQUEST_TIMEOUT = 25      

PAST_YEAR_RANGE = (1985, 2000) 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

os.makedirs(GENERATED_ARTICLES_DIR, exist_ok=True)
os.makedirs(IMAGES_DIR, exist_ok=True) 

if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        logging.info("Google Gemini API client configured.")
    except Exception as e:
        logging.error(f"Failed to configure Google Gemini client. Error: {e}")
else:
    logging.warning("GOOGLE_API_KEY environment variable not set. LLM synthesis will not work.")

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
                    if not any(ext in item['link'].lower() for ext in [
                        '.zip', '.exe', '.jpg', '.png', '.gif', '.mp3', '.mp4', '.avi', 
                        'forum', 'forums', 'discussion', 'archive.org', 'support.google.com', 
                        'jobs.google.com', 'developers.google.com', 'policies.google.com', 
                        'privacy', 'legal', 'terms', 'about', 'contact', 'careers', 'sitemap.xml', 'robots.txt',
                        'github.com', 'aws.amazon.com', 'azure.microsoft.com', 'cloud.google.com', 
                        'openai.com', 'perplexity.ai', 'reddit.com', 'twitter.com', 'facebook.com', 'youtube.com', 
                        'blog', '/blog/', 'newsroom', '/newsroom/', 'press', '/press/',
                        'login', 'signup', 'subscribe', 'cart', 'shop', 'cdn.', 'assets.', 'static.', 'media.'
                        ]):
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
        logging.error(f"JSON decode error from Google CSE response: {e}. Response preview: {response.text[:200]}...")
        return []

def get_header_image_url(article_id):
    try:
        random_unsplash_url = f"https://source.unsplash.com/random/1080x720?technology,abstract,futuristic,circuit,neural,network,data,ai,robotics,vintage,retro,history,cyberpunk&sig={random.randint(1,1000000)}" 
        return random_unsplash_url
    except Exception as e:
        logging.warning(f"Could not get random Unsplash image: {e}")
        return "https://images.unsplash.com/photo-1445160307478-288488e5da27?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w3NjUwNzN8MHwxfHJhbmRvbXx8fHx8fHx8fDE3NTA2ODE1NzB8&ixlib=rb-4.1.0&q=80&w=1080" 

def is_ai_relevant(title, text):
    title_lower = title.lower()
    text_lower = text.lower()
    for keyword in AI_KEYWORDS:
        if keyword in title_lower or keyword in text_lower:
            return True
    return False

def scrape_full_article_text(article_url):
    try:
        config = newspaper.Config()
        config.browser_user_agent = 'Mozilla/50 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        config.request_timeout = REQUEST_TIMEOUT
        config.fetch_images = False 
        config.MAX_FILE_MEM_KB = 5000 
        config.browser = "chrome" 
        config.memoize_articles = False 

        article = newspaper.Article(article_url, config=config)
        article.download()
        article.parse()
        
        if not article.title or not article.text or len(article.text) < 250: 
            logging.info(f"Skipping {article_url}: Missing title or too short content for synthesis (len {len(article.text) if article.text else 0}).")
            return None

        if not is_ai_relevant(article.title, article.text):
            logging.info(f"Skipping {article_url}: Not AI relevant after full content check for synthesis.")
            return None
        
        if article.publish_date:
            target_start_date = datetime(PAST_YEAR_RANGE[0], 1, 1)
            target_end_date = datetime(PAST_YEAR_RANGE[1] + 1, 1, 1) - timedelta(days=1)
            
            if not (target_start_date <= article.publish_date <= target_end_date):
                logging.info(f"Skipping {article_url}: Publish date {article.publish_date.strftime('%Y-%m-%d')} is outside target range {PAST_YEAR_RANGE[0]}-{PAST_YEAR_RANGE[1]}.")
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
    if not GOOGLE_API_KEY: 
        logging.error("Google Gemini client not configured. Cannot generate analysis.")
        return None

    if not scraped_articles:
        logging.warning("No articles provided for AI analysis.")
        return None

    combined_content = ""
    for i, article in enumerate(scraped_articles):
        combined_content += f"--- Source Article {i+1} ---\n"
        combined_content += f"Title: {article['title']}\n"
        combined_content += f"URL: {article['url']}\n"
        combined_content += f"Published Date (as scraped): {article['publish_date']}\n"
        combined_content += f"Source Domain: {article['source']}\n"
        combined_content += f"Content Excerpt:\n{article['text'][:3000]}...\n\n" 
    
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
                max_output_tokens=2500, 
                temperature=0.8, 
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
    generated_title = f"AI in the Era of {primary_scrape_date_str}"
    generated_hook = "An insightful look back at historical AI concepts and their prescience."
    main_article_body_html = generated_content 
    
    match_h1 = re.search(r'<h1[^>]*>(.*?)<\/h1>', generated_content, re.IGNORECASE | re.DOTALL)
    if match_h1:
        generated_title = match_h1.group(1).strip()
        main_article_body_html = re.sub(r'<h1[^>]*>.*?<\/h1>', '', main_article_body_html, flags=re.IGNORECASE | re.DOTALL, count=1).strip()

    match_hook = re.search(r'<p\s+class="hook"[^>]*>(.*?)<\/p>', main_article_body_html, re.IGNORECASE | re.DOTALL)
    if match_hook:
        generated_hook = match_hook.group(1).strip()
        main_article_body_html = re.sub(r'<p\s+class="hook"[^>]*>.*?<\/p>', '', main_article_body_html, flags=re.IGNORECASE | re.DOTALL, count=1).strip()
    
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
<style>
:root{{{{--grid-color:rgba(200,200,200,0.1);--text-color:#E0E0E0;--bg-color:#111;--panel-bg-color:rgba(18,18,18,0.9);--panel-border-color:#444;--highlight-color:#00BFFF;--quote-border-color:#4A90E2}}}}
body{{{{font-family:'Lora',serif;line-height:1.8;color:var(--text-color);background-color:var(--bg-color);background-image:linear-gradient(var(--grid-color) 1px,transparent 1px),linear-gradient(90deg,var(--grid-color) 1px,transparent 1px);background-size:40px 40px;margin:0;padding:2rem}}}}
.main-container{{{{max-width:800px;margin:2rem auto}}}}
.main-header{{{{text-align:center;margin-bottom:2rem}}}}
h1{{{{font-family:'Source Code Pro',monospace;font-size:2.8rem;font-weight:700;color:#FFF;text-transform:uppercase;letter-spacing:.3em;word-spacing:.5em;margin:0;padding-left:.3em}}}}
.main-header p{{{{font-family:'Source Code Pro',monospace;font-size:.9rem;text-transform:uppercase;letter-spacing:.2em;color:#FFF;margin-top:1rem}}}}
.article-image{{{{width:100%;height:auto;margin-bottom:2rem;border:1px solid var(--panel-border-color)}}}}
.content-panel{{{{background-color:var(--panel-bg-color);border:1px solid var(--panel-border-color);padding:2.5rem;backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px)}}}}
.content-panel p,.content-panel li{{{{font-size:1.1rem}}}}
.content-panel .hook{{{{font-size:1.3rem;line-height:1.7;font-style:italic;color:#BDBDBD;margin-bottom:2rem}}}}
.content-panel h3{{{{font-family:'Source Code Pro',monospace;font-size:1.5rem;margin-top:2.5rem;color:#FFF}}}}
.content-panel blockquote{{{{font-family:'Lora',serif;font-size:1.4rem;font-style:italic;font-weight:700;border-left:4px solid var(--quote-border-color);padding-left:1.5rem;margin:2.5rem 0;color:#A7C7E7}}}}
.content-panel .highlight{{{{background-color:rgba(0,191,255,0.15);padding:.1rem .3rem}}}}
.content-panel .section-divider{{{{border:0;height:1px;background-color:#444;margin:3rem 0}}}}
.cta-container{{{{background-color:var(--panel-bg-color);border:1px solid var(--panel-border-color);backdrop-filter:blur(8px);margin-top:2rem;text-align:center}}}}
.cta-container .panel-title-bar{{{{background-color:var(--panel-border-color);color:#FFF;padding:.5rem 1rem;font-family:'Source Code Pro',monospace;font-weight:700;text-transform:uppercase;letter-spacing:.1em}}}}
.cta-container .panel-body{{{{padding:1.5rem}}}}
.button-container{{{{display:flex;justify-content:center;gap:1.5rem;margin-top:2rem;flex-wrap:wrap}}}}
.action-button{{{{font-family:'Source Code Pro',monospace;font-weight:700;text-transform:uppercase;letter-spacing:.1em;background-color:transparent;color:var(--highlight-color);border:2px solid var(--highlight-color);padding:.7rem 1.2rem;font-size:.9rem;text-decoration:none;transition:background-color .2s,color .2s}}}}
.action-button:hover{{{{background-color:var(--highlight-color);color:var(--bg-color)}}}}
</style></head>
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
    """Loads the index of previously generated analysis articles."""
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                logging.warning(f"Corrupt or empty {INDEX_FILE}. Starting fresh.")
                return []
    return []

def save_index(index_data):
    """Saves the updated index of generated analysis articles."""
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(index_data, f, indent=2, ensure_ascii=False)

def main():
    generated_analyses_index = load_existing_index()
    
    analyses_added_this_run = 0
    attempts = 0
    
    logging.info("Starting Google CSE + Google Gemini AI Time Capsule Generation run (AI News Detective Mode)...")

    # --- Diagnostic: List available Gemini models ---
    logging.info("Attempting to list available Gemini models for debugging:")
    try:
        found_target_model = False
        for m in genai.list_models():
            if "generateContent" in m.supported_generation_methods:
                logging.info(f"  Available Model: {m.name} (supports generateContent)")
                if m.name == GEMINI_MODEL:
                    found_target_model = True
            else:
                logging.debug(f"  Available Model: {m.name} (does NOT support generateContent)")
        
        if not found_target_model:
            logging.error(f"Configured model '{GEMINI_MODEL}' was NOT found in the list of models supporting generateContent for your API Key. Please check API key permissions/restrictions or Google Cloud billing setup.")
            time.sleep(10)
            return 
        else:
            logging.info(f"Configured model '{GEMINI_MODEL}' IS found and supports generateContent. Proceeding.")

    except Exception as e:
        logging.error(f"Failed to list Gemini models: {e}. This might indicate API key/billing issue.")
        logging.info("Exiting due to Gemini model listing failure.")
        time.sleep(10)
        return 
    # --- End Diagnostic ---
    
    month_names = ["January", "February", "March", "April", "May", "June", 
                   "July", "August", "September", "October", "November", "December"]

    while analyses_added_this_run < 1 and attempts < MAX_SEARCH_ATTEMPTS_PER_RUN: 
        attempts += 1
        
        random_month_date = get_random_past_month(*PAST_YEAR_RANGE)
        primary_scrape_date_str = f"{month_names[random_month_date.month - 1]} {random_month_date.year}"
        logging.info(f"Attempt {attempts}/{MAX_SEARCH_ATTEMPTS_PER_RUN}: Searching for raw articles from: {primary_scrape_date_str}")
        
        # --- Aggressively Targeted Search Query for 1985-2000 Academic/Journal Content ---
        # --- FIX: Corrected the `join` syntax here ---
        ai_search_terms = " OR ".join(f'"{kw}"' for kw in AI_KEYWORDS) 
        publication_search_terms = " OR ".join(f'"{kw}"' for kw in PUBLICATION_KEYWORDS) 

        targeted_domains = [
            "aaai.org", "jair.org", 
            "mit.edu", "stanford.edu", "cmu.edu", "berkeley.edu", 
            "ieee.org", "spectrum.ieee.org", "acm.org", "dl.acm.org", 
            "sciencedirect.com", "onlinelibrary.wiley.com", 
            "wired.com", "sciencedaily.com", 
            "ijcai.org", "nips.cc", "icml.cc" 
        ]
        site_operators = " OR ".join(f"site:{d}" for d in targeted_domains)

        search_query = f'({ai_search_terms}) ({publication_search_terms}) {primary_scrape_date_str} ({site_operators})'
        
        logging.debug(f"  Generated search query: {search_query}")
        
        google_cse_results = fetch_google_cse_results(search_query, num_results=10) 
        
        if not google_cse_results:
            logging.info(f"  No relevant search results found in Google CSE for {primary_scrape_date_str} with current query. Trying next date.")
            time.sleep(2) 
            continue

        random.shuffle(google_cse_results) 
        
        scraped_articles_for_synthesis = []
        for i, result in enumerate(google_cse_results):
            if len(scraped_articles_for_synthesis) >= MAX_SCRAPED_ARTICLES_FOR_SYNTHESIS:
                break 

            if any(term in result['link'].lower() for term in [
                'forum', 'forums', 'discussion', 'comments', 'blog', 'index.html', '/tag/', '/category/', 
                'masthead', 'contact', 'about', 'member', 'privacy', 'legal', 'jobs', 'careers', 
                '.css', '.js', '.xml', 'robots.txt', 'login', 'signup', 'subscribe', 'cart', 'shop',
                'github.com', 'aws.amazon.com', 'azure.microsoft.com', 'cloud.google.com', 
                'openai.com', 'perplexity.ai', 'reddit.com', 'twitter.com', 'facebook.com', 'youtube.com', 
                'newsroom', '/newsroom/', 'press', '/press/', 'cdn.', 'assets.', 'static.', 'media.'
                ]) or (result['link'].count('/') <= 3 and any(d in result['link'].lower() for d in ['org', 'edu', 'com', 'net'])): 
                logging.debug(f"  Skipping {result['link']}: Appears to be a non-article page type from URL pattern or too generic base domain.")
                continue

            potential_ai = False
            combined_text_from_search = (result['title'] + " " + result['snippet']).lower()
            if any(keyword in combined_text_from_search for keyword in AI_KEYWORDS):
                potential_ai = True

            if not potential_ai:
                logging.debug(f"  Skipping {result['link']}: No strong AI keywords in title/snippet from search result.")
                continue

            logging.info(f"  Attempting to scrape raw text from potential AI article: {result['link']}")
            article_content = scrape_full_article_text(result['link'])
            
            if article_content:
                scraped_articles_for_synthesis.append(article_content)
                logging.info(f"  Successfully scraped raw text from '{article_content['title']}'. Scraped count: {len(scraped_articles_for_synthesis)}")
            else:
                logging.info(f"  Failed to scrape or validate content from {result['link']}.")
            
            time.sleep(1.5) 

        if not scraped_articles_for_synthesis:
            logging.info(f"  No suitable articles scraped for synthesis from {primary_scrape_date_str} after full scraping attempts. Trying next date.")
            time.sleep(3) 
            continue

        logging.info(f"  Proceeding to generate AI analysis using Gemini for {len(scraped_articles_for_synthesis)} articles scraped from {primary_scrape_date_str}.")
        generated_html_content = generate_ai_analysis(scraped_articles_for_synthesis, primary_scrape_date_str)

        if generated_html_content:
            timestamp_slug = datetime.now().strftime("%Y%m%d%H%M%S")
            filename = f"ai_analysis_{timestamp_slug}.html"
            html_path = os.path.join(GENERATED_ARTICLES_DIR, filename)
            
            header_image_url = get_header_image_url(filename) 

            full_article_html = create_full_html_article(
                generated_html_content,
                primary_scrape_date_str, 
                header_image_url
            )
            
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(full_article_html)
            
            analysis_data = {
                "id": f"analysis_{timestamp_slug}",
                "title": f"AI in the Era of {primary_scrape_date_str}", 
                "summary": "An insightful look back at historical AI concepts and their prescience.", 
                "html_path": html_path.replace("\\", "/"), 
                "generated_date": datetime.now().isoformat(),
                "original_sources_count": len(scraped_articles_for_synthesis),
                "featured_image": header_image_url
            }
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
            logging.warning("  Failed to generate analysis content with Gemini for this attempt.")
        
        time.sleep(5) 

    save_index(generated_analyses_index)
    logging.info(f"Finished run. Added {analyses_added_this_run} new analysis articles. Total analyses in index: {len(generated_analyses_index)}")

if __name__ == "__main__":
    main()
