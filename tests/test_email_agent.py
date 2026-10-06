import asyncio
import json
import logging
import os
from datetime import datetime

from leoai.ai_core import GeminiClient
from leoai.ai_index import ContentIndex

from leoai.email_sender import EmailSender
from leoai.rag_context_utils import get_base_context


logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("content_recommendation")

def pretty(obj):
    """Helper for beautiful JSON printing."""
    return json.dumps(obj, indent=2, ensure_ascii=False)


async def main():
    gemini = GeminiClient()
    indexer = ContentIndex(gemini)

    # --- Sample Pages to index ---
    sample_pages = {
        1: """
        Chapter 1: Customer 360 Overview
        - Identity Resolution
        - Data Ingestion
        - Analytics & AI
        """,
        2: """
        Chapter 2: Marketing Automation
        - Campaign Orchestration
        - Personalization
        - A/B Testing
        """,
        3: """
        Chapter 3: Data Architecture
        - Data Lakes
        - Data Warehouses
        - Real-Time Streaming
        """,
        4: """
        Chapter 4: Machine Learning Use Cases
        - Recommendation Systems
        - Predictive Analytics
        - Natural Language Processing
        """,
        5: """
        Chapter 5: Governance & Compliance
        - Data Privacy
        - Security
        - Regulatory Frameworks
        """
    }

    # --- Index sample pages ---
    logger.info("=== Indexing content pages ===")
    for page_num, text in sample_pages.items():
        toc = indexer.extract_toc(text)
        page_id = indexer.save_page(page_num, toc)
        logger.info(f"Page {page_num} saved with ID: {page_id}")

    # --- User query (personal interest) ---
    query = "Data Privacy"
    logger.info(f"\n=== Querying similar content for: '{query}' ===")
    results = indexer.query_similar(query, top_k=3)
    logger.info(pretty(results))



    # --- Prepare recommendation list for the email ---
    recommended_contents = []
    for row in results:
        similarity_score = max(0, 1 - float(row.get("distance", 0)))  # normalize to 0–1 range

        # Extract and parse the toc
        toc_data = row.get("toc")
        if isinstance(toc_data, dict):
            raw_text = toc_data.get("raw_text", "")
            # Try to extract the JSON content from the triple backticks
            if raw_text.startswith("```json"):
                try:
                    # Remove backticks and parse JSON
                    json_str = raw_text.strip("` \n").replace("json", "", 1).strip()
                    parsed_toc = json.loads(json_str)
                    title = parsed_toc.get("title", "Untitled Section")
                except Exception:
                    title = "Untitled Section"
            else:
                title = raw_text or "Untitled Section"
        else:
            title = str(toc_data) or "Untitled Section"

        # Create a human-readable summary
        summary = f"This section explores **{title}** and its key ideas in depth."

        recommended_contents.append({
            "title": title,
            "summary": summary,
            "url": f"https://yourapp.com/content/{row.get('id')}",
            "similarity_score": round(similarity_score, 3),
        })


    # --- Email context ---
    context = get_base_context()
    context["user_profile"]["first_name"] = "Trieu"
    context["user_context"]["location"] = "Saigon"
    context["user_context"]["datetime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    context["user_context"]["current_year"] = datetime.now().year
    context["recommended_contents"] = recommended_contents

    # --- Send email ---
    logger.info("\n=== Sending personalized content email ===")
    email_sender = EmailSender()
    success = await email_sender.send(
        to_email="tantrieuf31.database@gmail.com",
        subject="Your Personalized AI Content Recommendations",
        template_name="content_recommendation.html",
        context=context,
    )

    logger.info(f"Email sent: {success}")


if __name__ == "__main__":
    asyncio.run(main())
