import logging
import markdown
import asyncio
from typing import Optional, List, Union, Any
from leoai.ai_core import GeminiClient, get_embedding_model
from leoai.rag_db_manager import ChatDBManager
from leoai.rag_context_manager import ContextManager
from leoai.rag_prompt_builder import AgentOrchestrator
from leoai.rag_knowledge_manager import KnowledgeRetriever
from main_config import REDIS_CLIENT

logger = logging.getLogger("RAGAgent")
logger.setLevel(logging.INFO)


class RAGAgent:
    def __init__(self, gemini_client: Optional[Union[GeminiClient, Any]] = None):
        self.client = gemini_client or GeminiClient()
        self.embedding_model = get_embedding_model()
        self.db = ChatDBManager(self.embedding_model)
        self.context = ContextManager(self.embedding_model, self.client, self.db)
        self.knowledge = KnowledgeRetriever(self.embedding_model)
        self.agent_orchestrator = AgentOrchestrator()

    async def process_chat_message(
        self,
        user_id: str,
        user_message: str,
        cdp_profile_id: Optional[str] = None,
        persona_id: Optional[str] = 'personal_assistant',
        touchpoint_id: Optional[str] = None,
        target_language: str = "Vietnamese",
        answer_in_format: str = "text",
        temperature_score: float = 0.85,
        keywords: Optional[List[str]] = None,
    ) -> str:
        try:
            try:
                # 1️⃣ Save user message (sync)
                logger.info(f"🧠 insert user message: {user_message}")
                await self.db.save_chat_message(
                    user_id=user_id,
                    role="user",
                    message=user_message,
                    cdp_profile_id=cdp_profile_id,
                    persona_id=persona_id,
                    touchpoint_id=touchpoint_id,
                    keywords=keywords,
                )
            except Exception as e:
                logger.error(f"❌ Failed to save user message to DB: {e}")

            # 2️⃣ Build summarized context (async)
            summarized_context = await self.context.build_context_summary(
                user_id, touchpoint_id, cdp_profile_id, user_message
            )

            # 3️⃣ Cache user info in Redis
            user_profile = summarized_context.get("user_profile", {})
            first_name = user_profile.get("first_name")
            if first_name:
                REDIS_CLIENT.hset(user_id, mapping={"profile_id": "", "name": first_name})

            # 4️⃣ Build contextual prompt
            prompt_router = self.agent_orchestrator.build_prompt(
                user_message, summarized_context, target_language, persona_id
            )

            logger.info(f"🧠 Detected purpose: {prompt_router.purpose}")
            logger.info(f"📝 Prompt snippet: {prompt_router.prompt_text[:200]}...")

            # 5️⃣ Generate AI answer (runs sync client safely in thread)
            final_answer = await self._safe_generate(prompt_router, temperature_score)

            # 6️⃣ Save AI response
            if prompt_router.purpose == "generate_text":
                logger.info(f"🧠 insert bot message: {final_answer}")
                await self.db.save_chat_message(
                    user_id, "bot", final_answer, cdp_profile_id, persona_id, touchpoint_id
                )

            # 7️⃣ Return formatted answer
            if answer_in_format == "html":
                return markdown.markdown(final_answer)
            return final_answer

        except Exception as e:
            logger.exception("❌ RAG pipeline error")
            return f"I'm sorry, but something went wrong: {e}"

    async def _safe_generate(self, prompt_router, temperature_score: float) -> str:
        """
        Safely execute GeminiClient methods in async context.
        Supports both sync and async method types.
        """
        # Select correct generation method
        if prompt_router.purpose == "generate_report":
            method = self.client.generate_report
        else:
            method = self.client.generate_content

        # Handle async vs sync automatically
        if asyncio.iscoroutinefunction(method):
            return await method(prompt_router.prompt_text, temperature=temperature_score)
        else:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, lambda: method(prompt_router.prompt_text, temperature=temperature_score)
            )
