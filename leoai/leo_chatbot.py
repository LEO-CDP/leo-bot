
import datetime
from functools import lru_cache
from leoai.ai_core import AIClient

TEMPERATURE_SCORE = 0.86

@lru_cache(maxsize=1)
def get_ai_client() -> AIClient:
    return AIClient()

# the main function to ask LEO
def ask_question(context: str = '', answer_in_format: str = '', target_language: str = '', question: str = 'Hi', temperature_score = TEMPERATURE_SCORE ) -> str:
    context = context + '.Today, current date and time is ' + datetime.datetime.now().strftime("%c")
    prompt = f"""You are LEO, a helpful AI assistant.
Answer the question using the provided context. If it is insufficient, say so.
Always respond in {target_language or "the user's language"}.
Requested format: {answer_in_format or "text"}
Current date and time: {datetime.datetime.now().strftime("%c")}

Context:
{context}

Question:
{question}
"""
    return get_ai_client().generate_content(prompt, temperature=temperature_score)
