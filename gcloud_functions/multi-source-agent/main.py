import functions_framework
from flask import Request, Response
import traceback

from cors import build_response, build_preflight_response
from agent_service import process

# -------------------------------------------------------------
# Hàm Xử lý HTTP Endpoint
# -------------------------------------------------------------

@functions_framework.http
def main(request: Request):
    """
    Xử lý yêu cầu HTTP (OPTIONS/POST) và điều phối đến hàm process.
    """
    origin = request.headers.get('Origin')

    # 1. Xử lý Preflight OPTIONS Request
    if request.method == 'OPTIONS':
        print(f"Handling OPTIONS request from Origin: {origin}")
        return build_preflight_response(origin)

    # 2. Xử lý POST Request thực tế
    data = request.get_json(silent=True) or {}
    print("INPUT_DATA:", data)

    urls = data.get("urls", [])
    question = data.get("question", "")

    # Validate input
    if not urls or not question:
        return build_response(
            {"error": "Please set required fields: urls, question"},
            status_code=400,
            origin=origin
        )

    try:
        # Gọi hàm logic nghiệp vụ
        answer = process(urls, question)

        return build_response(
            {"answer": answer},
            status_code=200,
            origin=origin
        )

    except ValueError as e:
        # Lỗi về API Key hoặc cấu hình
        print("🔥 Configuration Error:", e)
        return build_response(
            {"error": f"Configuration error: {str(e)}"},
            status_code=500,
            origin=origin
        )

    except Exception as e:
        # Log đầy đủ traceback
        print("🔥 Exception in main():", e)
        traceback.print_exc()

        return build_response(
            {"error": "Internal Server Error"},
            status_code=500,
            origin=origin
        )
