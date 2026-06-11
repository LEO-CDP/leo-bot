# Import các thành phần logic từ module đã refactor
from multi_source_agent import (
    AppConfig,
    CacheStorage,
    ContextCacheManager,
    MultiSourceAgent,
    get_gemini_client
)

# -------------------------------------------------------------
# Hàm Logic Nghiệp Vụ Chính
# -------------------------------------------------------------

def process(urls: list[str], question: str) -> str:
    """
    Chứa logic chính: khởi tạo agent, quản lý cache và trả lời câu hỏi.
    
    Args:
        urls: Danh sách các URL nguồn.
        question: Câu hỏi cần trả lời.
        
    Returns:
        Câu trả lời tổng hợp từ Agent.
    
    Raises:
        ValueError: Nếu API Key không được thiết lập.
        Exception: Các lỗi khác trong quá trình xử lý (như download, upload, Gemini API).
    """
    # Khởi tạo client, config và các thành phần
    client = get_gemini_client()
    config = AppConfig()
    storage = CacheStorage(config)
    manager = ContextCacheManager(client, config, storage)
    agent = MultiSourceAgent(client, config, manager)

    # Hỏi Agent
    answer = agent.ask(urls, question)
    
    return answer
