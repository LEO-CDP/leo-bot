import sqlite3
from _bootstrap import PROJECT_ROOT
from leoai.ai_core import AIClient

llm = AIClient()

# === STEP 2: Setup test SQLite DB ===
conn = sqlite3.connect(":memory:")  # in-memory DB for testing
cur = conn.cursor()

# Example table
cur.execute("""
CREATE TABLE employees (
    id INTEGER PRIMARY KEY,
    name TEXT,
    department TEXT,
    salary INTEGER
)
""")
cur.executemany("""
INSERT INTO employees (name, department, salary)
VALUES (?, ?, ?)
""", [
    ("Alice", "Engineering", 120000),
    ("Bob", "Sales", 90000),
    ("Charlie", "Engineering", 110000),
    ("Diana", "HR", 80000)
])
conn.commit()

# === STEP 3: SQL Agent prompt ===
def generate_sql(user_request: str) -> str:
    system_prompt = (
        "You are a helpful assistant that converts natural language questions into SQL queries. "
        "Only output SQL without explanations. The database is SQLite and follows standard SQL."
    )
    prompt = f"{system_prompt}\nUser request: {user_request}\nSQL:"
    return llm.generate_content(prompt, temperature=0)

# === STEP 4: Agent loop ===
while True:
    question = input("\nAsk a question about employees (or 'exit'): ")
    if question.lower() == "exit":
        break

    sql_query = generate_sql(question)
    print("\nGenerated SQL:\n", sql_query)

    try:
        cur.execute(sql_query)
        results = cur.fetchall()
        print("Results:", results)
    except Exception as e:
        print("SQL execution error:", e)

conn.close()