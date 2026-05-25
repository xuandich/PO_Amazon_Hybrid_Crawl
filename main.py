# main.py - Script chính
import sys
import pandas as pd
from pathlib import Path
from crawler import AmazonCrawler

try:
    from config import INPUT_FILE, MAX_URLS, MAX_WORKERS
except ImportError:
    INPUT_FILE = "input/amazon_FR.xlsx"
    MAX_URLS = None
    MAX_WORKERS = 10

def read_urls() -> list:
    """Đọc danh sách URL từ file Excel"""
    if not Path(INPUT_FILE).exists():
        print(f"❌ Không tìm thấy file: {INPUT_FILE}")
        return []
    
    print(f"\n📖 Đang đọc file: {INPUT_FILE}")
    df = pd.read_excel(INPUT_FILE, header=None)
    urls = [row[0] for _, row in df.iterrows() if isinstance(row[0], str) and row[0].startswith('http')]
    
    if MAX_URLS and MAX_URLS > 0:
        urls = urls[:MAX_URLS]
    
    print(f"✅ Đã đọc {len(urls)} URLs")
    return urls

def main():
    # Lấy số luồng từ tham số dòng lệnh
    max_workers = MAX_WORKERS
    if len(sys.argv) > 1:
        try:
            max_workers = int(sys.argv[1])
            print(f"📝 Số luồng: {max_workers}")
        except:
            pass
    
    # Đọc URLs
    urls = read_urls()
    if not urls:
        return
    
    # Khởi tạo crawler và chạy
    crawler = AmazonCrawler(max_workers=max_workers)
    crawler.run(urls)
    
    print("\n✅ HOÀN TẤT!")

if __name__ == "__main__":
    main()