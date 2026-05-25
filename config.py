# config.py
import os
from pathlib import Path

# ==================== CẤU HÌNH ĐƯỜNG DẪN ====================
INPUT_FILE = "input/amazon_FR.xlsx"
PROXY_FILE = "Proxy/buyproxies_List.xlsx"
OUTPUT_DIR = "output"
COOKIE_DIR = "cookies"

# ==================== CẤU HÌNH SCRAPE ====================
MAX_URLS = None  # None = tất cả, hoặc số cụ thể
MAX_CONCURRENT_TASKS = 10
MAX_WORKERS = 3  # Chỉ crawl 3 URL cùng lúc
REQUEST_TIMEOUT = 30

# Delay ngẫu nhiên (giây)
MIN_DELAY = 1
MAX_DELAY = 3

# ==================== CẤU HÌNH CURL_CFFI ====================
CURL_IMPRERSONATE = "chrome120"

# ==================== CẤU HÌNH LƯU KẾT QUẢ ====================
SAVE_ONLY_SUCCESS = True

# ==================== CẤU HÌNH PROXY ====================
ROTATION_STRATEGY = "random"

# ==================== CẤU HÌNH RETRY TƯNG URL ====================
MAX_RETRIES_PER_URL = 3  # Số lần thử tối đa (kể cả lần đầu)
RETRY_DELAY = 2  # Giây chờ giữa các lần retry
RETRY_ON_ERRORS = ["timeout", "connection", "http_403", "http_429", "http_503", "missing_data"]

# ==================== CẤU HÌNH RETRY All URL THẤT BẠI ====================
MAX_FINAL_RETRY = 3  # Số lần retry toàn bộ URL thất bại

# Tạo thư mục cần thiết
for dir_name in [OUTPUT_DIR, COOKIE_DIR, "input", "Proxy"]:
    Path(dir_name).mkdir(exist_ok=True)