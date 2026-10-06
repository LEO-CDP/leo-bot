from _bootstrap import PROJECT_ROOT
from leoai.ai_core import AIClient

text_vi = "iPhone 15 chả có gì mới, Apple Watch vẫn chán như mọi khi"

client = AIClient()

print(client.generate_content(
    "Translate this text into English and classify its sentiment as positive, "
    "neutral, or negative. Return the translation followed by the sentiment label.\n\n"
    f"{text_vi}",
    temperature=0,
))

text = '''As a product executive of more than 15 years, I find a lot of this lean product stuff to miss the mark. 
The book is okay for what it is, but lean product management doesn't really work well in practice except in particular UI based applications. 
And even then, companies that practice lean product management do a pretty terrible job 
with their interfaces given the amount of resources they have: examples in point: Amazon.com, Ebay, and Netflix.'''
print(client.generate_content(
    "Classify this text's sentiment as positive, neutral, or negative. Return only the label.\n\n"
    f"{text}",
    temperature=0,
))

