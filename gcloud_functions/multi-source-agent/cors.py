import os
from flask import Response, jsonify

def load_env_override(path=".env"):
    if not os.path.exists(path):
        return
    
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")

                # Force override
                os.environ[key] = value

load_env_override()

# -------------------------------------------------------------
# Cấu hình CORS
# -------------------------------------------------------------

# Load ALLOWED_ORIGINS từ biến môi trường (.env hoặc Cloud Run)
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in _raw_origins.split(",")
    if origin.strip()
]

print("Loaded ALLOWED_ORIGINS:", ALLOWED_ORIGINS)


def add_cors_headers(response: Response, origin: str | None) -> Response:
    """Thêm header CORS nếu origin hợp lệ."""
    if origin and origin in ALLOWED_ORIGINS:
        response.headers.add("Access-Control-Allow-Origin", origin)
        response.headers.add("Access-Control-Allow-Credentials", "true")
        response.headers.add("Access-Control-Allow-Methods", "POST, OPTIONS")
        response.headers.add("Access-Control-Allow-Headers", "Content-Type, Authorization")
    return response


def build_response(data: dict, status_code: int = 200, origin: str | None = None) -> Response:
    """Tạo đối tượng Response của Flask, thêm header CORS."""
    response = jsonify(data)
    response.status_code = status_code
    return add_cors_headers(response, origin)


def build_preflight_response(origin: str | None) -> Response:
    """Response cho OPTIONS."""
    response = Response(status=204)  # No Content
    if origin and origin in ALLOWED_ORIGINS:
        response.headers.add("Access-Control-Allow-Origin", origin)
        response.headers.add("Access-Control-Allow-Methods", "POST, OPTIONS")
        response.headers.add("Access-Control-Allow-Headers", "Content-Type, Authorization")
        response.headers.add("Access-Control-Max-Age", "3600")
        response.headers.add("Access-Control-Allow-Credentials", "true")
    return response
