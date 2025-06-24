// ai-time-capsule.js
document.addEventListener('DOMContentLoaded', () => {
    const articlesGrid = document.getElementById('ai-articles-grid');
    const articlesDataUrl = 'ai_articles.json'; // Path to your JSON data

    async function loadArticles() {
        try {
            const response = await fetch(articlesDataUrl);
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            const articles = await response.json();
            
            // Sort articles by publish date (newest first for the "time capsule" to show most recent additions first)
            articles.sort((a, b) => new Date(b.publish_date) - new Date(a.publish_date));

            articlesGrid.innerHTML = ''; // Clear loading indicator

            if (articles.length === 0) {
                articlesGrid.innerHTML = '<p>No AI articles found yet. Please trigger the scraper!</p>';
                return;
            }

            articles.forEach(article => {
                const articleCard = document.createElement('div');
                articleCard.className = 'ai-article-card';

                if (article.image_path) {
                    const img = document.createElement('img');
                    img.src = article.image_path;
                    img.alt = article.title;
                    img.onerror = function() {
                        this.style.display = 'none'; // Hide broken images
                    };
                    articleCard.appendChild(img);
                }

                const contentDiv = document.createElement('div');
                contentDiv.className = 'ai-article-card-content';

                const title = document.createElement('h3');
                const titleLink = document.createElement('a');
                titleLink.href = article.wayback_url; // Link to Wayback Machine snapshot
                titleLink.target = "_blank"; // Open in new tab
                titleLink.rel = "noopener noreferrer"; // Security best practice
                titleLink.textContent = article.title;
                title.appendChild(titleLink);
                contentDiv.appendChild(title);

                const summary = document.createElement('p');
                summary.textContent = article.summary;
                contentDiv.appendChild(summary);

                articleCard.appendChild(contentDiv);

                const metaDiv = document.createElement('div');
                metaDiv.className = 'ai-article-meta';
                metaDiv.innerHTML = `
                    <span>Source: ${article.source}</span>
                    <span>Date: ${new Date(article.publish_date).toLocaleDateString()}</span>
                `;
                articleCard.appendChild(metaDiv);


                articlesGrid.appendChild(articleCard);
            });

        } catch (error) {
            console.error("Could not load AI articles data:", error);
            articlesGrid.innerHTML = '<p>Error loading AI articles. Please try again later.</p>';
        }
    }

    loadArticles();
});