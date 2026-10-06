
from leoai.ai_core import AIClient


def analyze_sentiment(text: str) -> str:
    """Classify sentiment through the configured hosted AI provider."""
    prompt = (
        "Classify the sentiment of the following text as positive, neutral, or negative. "
        "Return only the label.\n\n"
        f"Text: {text}"
    )
    return AIClient().generate_content(prompt, temperature=0)
