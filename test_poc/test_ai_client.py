from _bootstrap import PROJECT_ROOT
from leoai.ai_core import AIClient


client = AIClient()
print(client.generate_content(
    "What is your favourite condiment? Do you have mayonnaise recipes?",
    temperature=0.7,
))