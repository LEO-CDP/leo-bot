import asyncio
import uuid
from leoai.rag_agent import RAGAgent


async def run_test_case(question: str, persona_id: str, touchpoint_id: str, target_language: str, keywords=None):
    """Helper to run a single test case with logging."""
    user_id = str(uuid.uuid4())
    rag_agent = RAGAgent()

    print(f"\n🧪 [TEST] Question: {question}")
    print(f"👤 User ID: {user_id}")
    print(f"🗣 Language: {target_language}\n")

    answer = await rag_agent.process_chat_message(
        user_id=user_id,
        user_message=question,
        persona_id=persona_id,
        touchpoint_id=touchpoint_id,
        target_language=target_language,
        keywords=keywords or [],
        answer_in_format="html",
    )

    print("🧠 Answer:\n" + "-" * 60)
    print(answer)
    print("-" * 60 + "\n")


async def run_all_tests():
    persona_id = "test-persona-001"
    touchpoint_id = "webchat-001"
    target_language = "English"

    # --- TEST 1: generate_plan ---
    question_plan = "Create a marketing plan for launching a new coffee product."
    await run_test_case(question_plan, persona_id, touchpoint_id, target_language)

    # --- TEST 2: generate_report ---
    question_report = "Generate a monthly sales report for the e-commerce dashboard."
    await run_test_case(question_report, persona_id, touchpoint_id, target_language)

    # --- TEST 3: generate_answer ---
    question_answer = "How can I update my payment method?"
    await run_test_case(question_answer, persona_id, touchpoint_id, target_language)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
