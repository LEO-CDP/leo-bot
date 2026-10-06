import asyncio
import logging

from leoai.ai_core import GeminiClient
from leoai.ai_knowledge_manager import GeminiEmbeddingProvider, KnowledgeManager, KnowledgeSource, KnowledgeSourceType

# ---------------------------------------------------------------------
# If run as module: small async demo (do not run in production)
# ---------------------------------------------------------------------

import asyncio
from leoai.ai_core import GeminiClient

client = GeminiClient()
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("test_chatbot")

# -----------------------------------------------
# Generate structured Markdown book description
# -----------------------------------------------
def generate_book_description(genre:str) -> str:

    # Markdown prompt
    prompt = (
        f"Tạo mô tả sách bằng tiếng Việt theo định dạng Markdown.\n"
        f"Output format:\n"
        f"# <Book Title>\n"
        f"**Author:** <Author Name>\n"
        f"**Genre:** {genre}\n"
        f"## Summary\n"
        f"- <Sentence 1>\n"
        f"- <Sentence 2>\n"
        f"- <Sentence 3>\n"
        f"Thực hiện theo định dạng trên, không thêm text ngoài mẫu."
    )

    answer = client.generate_content(prompt, temperature=0.9)

    # Basic parsing to ensure title, author, genre, summary exist
    lines = answer.splitlines()
    title, author, summary_lines = "", "", []

    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.lower().startswith("**author:**"):
            author = line.split(":", 1)[1].strip()
        elif line.startswith("- "):
            summary_lines.append(line)

    summary = "\n".join(summary_lines)

    # Return well-structured Markdown
    markdown_text = (
        f"# {title}\n"
        f"**Author:** {author}\n"
        f"**Genre:** {genre}\n"
        f"## Summary\n"
        f"{summary}"
    )
    return markdown_text


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

GENRES = [
    # Human mind & society
    "Psychology", "Philosophy", "Sociology", "History", "Politics",
    # Economics & business
    "Finance", "Economics", "Business", "Marketing", "Entrepreneurship",
    # Science & technology
    "Technology", "Data Science", "Physics", "Biology", "Computer Science",
    # Culture & creativity
    "Literature", "Art & Design", "Education", "Self-Improvement", "Non-Fiction"
]


# ---------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------

async def generate_sample_books(km: "KnowledgeManager", emb_provider: "GeminiEmbeddingProvider"):
    """Generate and ingest demo book data into the knowledge base."""
    source = KnowledgeSource(
        user_id="user-789",
        tenant_id="tenant-xyz",
        source_type=KnowledgeSourceType.UPLOADED_DOCUMENT,
        name="Book Demo",
        code_name="book_demo",
        metadata={"origin": "Gemini AI"}
    )

    logger.info("Generating structured book descriptions...")
    texts = [generate_book_description(genre) for genre in GENRES]
    combined_text = "\n\n".join(texts)

    created_source, count = await km.ingest_text_document(
        combined_text,
        source,
        emb_provider
    )

    logger.info(f"Inserted {count} chunks from {len(texts)} books.")
    print(f"✅ Generated and inserted {count} book chunks into the knowledge base.\n")


# ---------------------------------------------------------------------
# Query answering
# ---------------------------------------------------------------------

async def answer_user_query(km: "KnowledgeManager", emb_provider: "GeminiEmbeddingProvider", query: str):
    """Search knowledge and generate a contextual answer."""
    query_embedding = await emb_provider.embed_texts([query])
    query_emb = query_embedding[0]

    results = await km.search_similar_chunks(
        query_emb,
        top_k=5,
        tenant_id="tenant-xyz"
    )

    if not results:
        return "Không tìm thấy cuốn sách phù hợp nào."

    context_text = "\n\n".join([r[0].content for r in results])

    prompt = (
        f"Bạn là chuyên gia sách. Người dùng hỏi: '{query}'\n"
        f"Dựa trên cơ sở dữ liệu sách sau:\n{context_text}\n"
        f"Hãy gợi ý 1-2 cuốn sách phù hợp, trình bày bằng Markdown."
    )

    logger.info(f"Prompt:\n{prompt}\n")

    answer = client.generate_content(prompt, temperature=0.7)
    return str(answer)


# ---------------------------------------------------------------------
# Main chatbot loop
# ---------------------------------------------------------------------

async def chatbot_in_terminal():
    km = KnowledgeManager()
    emb_provider = GeminiEmbeddingProvider()

    print("Welcome to BookBot! Type 'generate sample data' to preload books, or ask a question.\nType 'exit' to quit.\n")

    while True:
        user_input = input("You: ").strip().lower()
        if user_input in ["exit", "quit"]:
            print("Goodbye!")
            break

        if "generate sample data" in user_input:
            await generate_sample_books(km, emb_provider)
        else:
            answer = await answer_user_query(km, emb_provider, user_input)
            print(f"\nBookBot: {answer}\n")


if __name__ == "__main__":
    asyncio.run(chatbot_in_terminal())