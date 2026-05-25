# main.py - Hoàn chỉnh với phân loại lỗi chi tiết
import asyncio

import pandas as pd
import random
import re
import signal
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from cookie_manager import CookieManager
from proxy_manager import ProxyManager
from data_manager import DataManager

try:
    from config import (
        INPUT_FILE, OUTPUT_DIR, MAX_URLS, SAVE_ONLY_SUCCESS,
        MIN_DELAY, MAX_DELAY, REQUEST_TIMEOUT, CURL_IMPRERSONATE,
        MAX_RETRIES_PER_URL, RETRY_DELAY, RETRY_ON_ERRORS,
        MAX_WORKERS, MAX_FINAL_RETRY
    )
except ImportError:
    INPUT_FILE = "input/amazon_FR.xlsx"
    OUTPUT_DIR = "output"
    MAX_URLS = None
    SAVE_ONLY_SUCCESS = True
    MIN_DELAY = 1
    MAX_DELAY = 3
    REQUEST_TIMEOUT = 30
    CURL_IMPRERSONATE = "chrome120"
    MAX_RETRIES_PER_URL = 3
    RETRY_DELAY = 2
    RETRY_ON_ERRORS = ["timeout", "connection", "http_403", "http_429", "http_503", "proxy_error", "missing_data"]
    MAX_WORKERS = 10
    MAX_FINAL_RETRY = 3

try:
    from curl_cffi import requests
    CURL_AVAILABLE = True
except ImportError:
    CURL_AVAILABLE = False
    import requests

thread_local = threading.local()

def get_thread_proxy_manager():
    if not hasattr(thread_local, 'proxy_manager'):
        thread_local.proxy_manager = ProxyManager()
    return thread_local.proxy_manager

class HybridAmazonScraper:
    def __init__(self, max_workers: int = MAX_WORKERS):
        self.cookie_manager = CookieManager()
        self.proxy_manager = ProxyManager()  
        self.results: List[Dict] = []
        self.failed_urls: List[Dict] = []
        self.is_running = True
        self.max_workers = max_workers
        self.lock = threading.Lock()
        self.start_time = None
        self.stats = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'retries': 0,
            'final_retries': 0
        }
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, sig, frame):
        print("\n\n⚠️ ĐANG DỪNG CHƯƠNG TRÌNH...")
        self.is_running = False
        self.save_results()
        sys.exit(0)
    
    def get_country_from_url(self, url: str) -> str:
        country_mapping = {
            'amazon.fr': 'France', 'amazon.de': 'Germany', 'amazon.co.uk': 'United Kingdom',
            'amazon.it': 'Italy', 'amazon.es': 'Spain', 'amazon.nl': 'Netherlands',
            'amazon.com': 'USA', 'amazon.ca': 'Canada', 'amazon.com.au': 'Australia',
        }
        for domain, country in country_mapping.items():
            if domain in url.lower():
                return country
        return "Unknown"
    
    def read_urls(self) -> List[str]:
        if not Path(INPUT_FILE).exists():
            print(f"❌ Không tìm thấy file: {INPUT_FILE}")
            return []
        
        print(f"\n📖 Đang đọc file: {INPUT_FILE}")
        df = pd.read_excel(INPUT_FILE, header=None)
        urls = [row[0] for _, row in df.iterrows() if isinstance(row[0], str) and row[0].startswith('http')]
        
        if MAX_URLS and MAX_URLS > 0:
            urls = urls[:MAX_URLS]
        
        print(f"✅ Đã đọc {len(urls)} URLs")
        print(f"⚡ Số luồng đồng thời: {self.max_workers}")
        return urls
    
    def should_retry(self, status: str) -> bool:
        for error in RETRY_ON_ERRORS:
            if error in status.lower():
                return True
        return False
    
    def classify_error(self, result: Dict, response_status: int = None, exception_msg: str = "") -> Dict:
        """Phân loại lỗi chi tiết"""
        status = result.get('status', 'unknown')
        
        # 1. LỖI KẾT NỐI / PROXY
        if 'timeout' in status.lower():
            return {
                'category': '⏰ TIMEOUT',
                'reason': 'Request quá thời gian chờ (30s)',
                'suggestion': 'Kiểm tra proxy hoặc tăng REQUEST_TIMEOUT'
            }
        elif 'connection' in status.lower() or 'proxy' in status.lower():
            return {
                'category': '🔌 LỖI KẾT NỐI',
                'reason': 'Không thể kết nối qua proxy',
                'suggestion': 'Proxy có thể đã chết, thử proxy khác'
            }
        elif 'http_403' in status.lower():
            return {
                'category': '🚫 BỊ CHẶN (403)',
                'reason': 'Amazon chặn request từ IP này',
                'suggestion': 'Đổi proxy hoặc giảm tốc độ crawl'
            }
        elif 'http_429' in status.lower():
            return {
                'category': '📊 QUÁ TẢI (429)',
                'reason': 'Gửi quá nhiều request trong thời gian ngắn',
                'suggestion': 'Tăng delay hoặc giảm số luồng concurrent'
            }
        elif 'http_503' in status.lower():
            return {
                'category': '🔧 LỖI SERVER (503)',
                'reason': 'Amazon server tạm thời quá tải',
                'suggestion': 'Thử lại sau, proxy vẫn tốt'
            }
        
        # 2. LỖI DỮ LIỆU
        elif 'missing_data' in status.lower():
            title = result.get('title')
            price = result.get('price')
            
            if not title and not price:
                return {
                    'category': '📭 KHÔNG CÓ DỮ LIỆU',
                    'reason': 'Không lấy được title và price',
                    'suggestion': 'Trang có thể thay đổi cấu trúc hoặc yêu cầu đăng nhập'
                }
            elif not title:
                return {
                    'category': '📭 THIẾU TITLE',
                    'reason': 'Không tìm thấy selector #productTitle',
                    'suggestion': 'Amazon có thể đã thay đổi cấu trúc HTML'
                }
            elif not price:
                return {
                    'category': '💰 THIẾU PRICE',
                    'reason': 'Không tìm thấy selector .a-price-whole',
                    'suggestion': 'Sản phẩm có thể hết hàng hoặc không hiển thị giá'
                }
        
        # 3. LỖI KHÁC
        else:
            return {
                'category': '❌ LỖI KHÁC',
                'reason': status[:100],
                'suggestion': 'Kiểm tra log chi tiết'
            }
    
    def get_product_info(self, url: str, cookie_string: str, proxy: Dict = None) -> Dict:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
            'Cookie': cookie_string,
        }
        
        proxies = None
        if proxy:
            if proxy.get('user') and proxy.get('pass'):
                proxy_url = f"http://{proxy['user']}:{proxy['pass']}@{proxy['host']}:{proxy['port']}"
            else:
                proxy_url = f"http://{proxy['host']}:{proxy['port']}"
            proxies = {"http": proxy_url, "https": proxy_url}
        
        try:
            if CURL_AVAILABLE:
                response = requests.get(url, impersonate=CURL_IMPRERSONATE, headers=headers, proxies=proxies, timeout=REQUEST_TIMEOUT)
            else:
                response = requests.get(url, headers=headers, proxies=proxies, timeout=REQUEST_TIMEOUT)
            
            if response.status_code != 200:
                return {"url": url, "title": None, "price": None, "status": f"http_{response.status_code}"}
            
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')
            
            title = None
            title_elem = soup.select_one('#productTitle')
            if title_elem:
                title = title_elem.get_text(strip=True)
            
            price = None
            price_elem = soup.select_one('.a-price-whole')
            if price_elem:
                price = price_elem.get_text(strip=True)
            else:
                price_elem = soup.select_one('.a-offscreen')
                if price_elem:
                    price_raw = price_elem.get_text(strip=True)
                    price_match = re.search(r'[\d\s,]+', price_raw)
                    if price_match:
                        price = price_match.group().strip()
            
            return {"url": url, "title": title, "price": price, "status": "success" if (title and price) else "missing_data"}
        except Exception as e:
            return {"url": url, "title": None, "price": None, "status": "error"}
    
    def scrape_single_url(self, url: str, idx: int, total: int, cookie_string: str, retry_round: int = 0) -> Dict:
        """Scrape một URL, kiểm tra quốc gia proxy nếu thất bại"""
        target_country = self.get_country_from_url(url)
        proxy_manager = get_thread_proxy_manager()
        
        print(f"\n{'─' * 70}")
        print(f"📦 [{idx}/{total}] {url[:80]}...")
        print(f"   🌍 Quốc gia mục tiêu: {target_country}")
        
        for attempt in range(1, MAX_RETRIES_PER_URL + 1):
            if not self.is_running:
                return None
            
            proxy = proxy_manager.get_next_proxy()
            
            if proxy:
                print(f"   🔒 Proxy: {proxy['host']}:{proxy['port']}")
                if proxy.get('user'):
                    print(f"   🔐 User: {proxy['user']}")
            else:
                print(f"   ⚠️ Không có proxy")
            
            delay = random.uniform(MIN_DELAY, MAX_DELAY)
            print(f"   ⏳ Delay {delay:.1f}s...")
            time.sleep(delay)
            
            result = self.get_product_info(url, cookie_string, proxy)
            
            if result['status'] == 'success':
                result['country'] = target_country
                result['proxy'] = proxy['host'] if proxy else None
                result['retries'] = attempt - 1
                result['retry_round'] = retry_round
                with self.lock:
                    self.stats['success'] += 1
                
                print(f"   ✅ THÀNH CÔNG: {result['title'][:50]}... - {result['price']}€")
                return result
            
            # ⭐ THÊM: Kiểm tra quốc gia proxy khi thất bại
            if proxy and result['status'] != 'success':
                # Chạy async trong thread pool
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                corrected = loop.run_until_complete(
                    self.verify_and_correct_proxy_country(proxy, url, result)
                )
                loop.close()
                
                if corrected:
                    print(f"   📌 Đã điều chỉnh proxy vào đúng quốc gia")
            
            # Phân loại lỗi chi tiết
            error_detail = self.classify_error(result)
            
            print(f"   ❌ {error_detail['category']}")
            print(f"      📝 Lý do: {error_detail['reason']}")
            print(f"      💡 Gợi ý: {error_detail['suggestion']}")
            
            if attempt < MAX_RETRIES_PER_URL and self.should_retry(result['status']):
                with self.lock:
                    self.stats['retries'] += 1
                print(f"   🔄 Thử lại với proxy khác sau {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)
            else:
                result['country'] = target_country
                result['proxy'] = proxy['host'] if proxy else None
                result['retries'] = attempt - 1
                result['retry_round'] = retry_round
                result['error_detail'] = error_detail
                with self.lock:
                    self.stats['failed'] += 1
                return result
        
        return {"url": url, "title": None, "price": None, "status": "failed_after_retries", "country": target_country}
    
    def calculate_eta(self, completed: int, total: int, elapsed: float) -> tuple:
        if completed == 0 or elapsed == 0:
            return "Đang tính toán...", 0
        
        avg_time_per_url = elapsed / completed
        speed_per_second = self.max_workers / avg_time_per_url if avg_time_per_url > 0 else 0
        remaining = total - completed
        eta_seconds = remaining / speed_per_second if speed_per_second > 0 else 0
        
        if eta_seconds < 60:
            eta_str = f"{eta_seconds:.0f} giây"
        elif eta_seconds < 3600:
            eta_str = f"{eta_seconds/60:.1f} phút"
        else:
            hours = eta_seconds / 3600
            minutes = (eta_seconds % 3600) / 60
            eta_str = f"{hours:.0f} giờ {minutes:.0f} phút"
        
        return eta_str, speed_per_second
    
    def scrape_batch(self, urls: List[str], retry_round: int = 0) -> List[Dict]:
        cookie_string = self.cookie_manager.get_cookie_string()
        if not cookie_string:
            print("❌ Chưa có cookie! Chạy: ./run.sh cookie")
            return []
        
        round_name = "LẦN " + str(retry_round + 1) if retry_round > 0 else "LẦN ĐẦU"
        print(f"\n🚀 {round_name}: SCRAPE {len(urls)} URLs với {self.max_workers} luồng")
        print("=" * 70)
        
        results = []
        completed = 0
        total = len(urls)
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self.scrape_single_url, url, idx, total, cookie_string, retry_round): url
                for idx, url in enumerate(urls, 1)
            }
            
            for future in as_completed(futures):
                completed += 1
                elapsed = time.time() - start_time
                eta_str, speed = self.calculate_eta(completed, total, elapsed)
                
                try:
                    result = future.result()
                    if result:
                        results.append(result)
                except Exception as e:
                    print(f"❌ Lỗi: {e}")
                
                if completed % 5 == 0 or completed == total:
                    percent = (completed / total) * 100
                    print(f"\n📊 TIẾN ĐỘ: {completed}/{total} ({percent:.1f}%)")
                    print(f"   ✅ Thành công: {self.stats['success']}")
                    print(f"   ❌ Thất bại: {self.stats['failed']}")
                    print(f"   🔄 Retry: {self.stats['retries']}")
                    print(f"   ⚡ Tốc độ: {speed:.1f} URL/giây")
                    print(f"   ⏱️  ETA: {eta_str}")
        
        return results
    
    def retry_failed_urls(self):
        if not self.failed_urls:
            print("\n✅ Không có URL thất bại để retry!")
            return
        
        print("\n" + "=" * 70)
        print(f"🔄 RETRY TOÀN BỘ {len(self.failed_urls)} URL THẤT BẠI")
        print("=" * 70)
        
        failed_url_list = [item['url'] for item in self.failed_urls if 'url' in item]
        
        for round_num in range(1, MAX_FINAL_RETRY + 1):
            print(f"\n🔁 LẦN RETRY {round_num}/{MAX_FINAL_RETRY}")
            
            self.stats['success'] = 0
            self.stats['failed'] = 0
            
            new_results = self.scrape_batch(failed_url_list, round_num)
            
            for new_result in new_results:
                for i, old_result in enumerate(self.results):
                    if old_result.get('url') == new_result.get('url'):
                        self.results[i] = new_result
                        break
            
            self.failed_urls = [r for r in new_results if r.get('status') != 'success']
            failed_url_list = [item['url'] for item in self.failed_urls if 'url' in item]
            
            if not self.failed_urls:
                print(f"\n✅ ĐÃ THÀNH CÔNG SAU {round_num} LẦN RETRY!")
                break
            
            print(f"\n⚠️ VẪN CÒN {len(self.failed_urls)} URL THẤT BẠI")
            self.stats['final_retries'] += 1
        
        if self.failed_urls:
            self.print_failed_urls_detail()
    
    def print_failed_urls_detail(self):
        """In chi tiết các URL thất bại và nguyên nhân"""
        print("\n" + "=" * 70)
        print("❌ DANH SÁCH URL THẤT BẠI (SAU KHI RETRY)")
        print("=" * 70)
        
        error_categories = {}
        for item in self.failed_urls[:20]:
            error_detail = item.get('error_detail', {})
            category = error_detail.get('category', '❌ LỖI KHÁC')
            error_categories[category] = error_categories.get(category, 0) + 1
            
            print(f"\n   🔗 {item.get('url', 'unknown')[:80]}...")
            print(f"      📝 {error_detail.get('reason', 'Không rõ nguyên nhân')}")
            print(f"      💡 {error_detail.get('suggestion', 'Kiểm tra lại')}")
        
        if len(self.failed_urls) > 20:
            print(f"\n   ... và {len(self.failed_urls) - 20} URL khác")
        
        print("\n📊 THỐNG KÊ LỖI:")
        for category, count in sorted(error_categories.items(), key=lambda x: x[1], reverse=True):
            print(f"   {category}: {count} URLs")
    
    def save_results(self):
        if not self.results:
            return
        
        if SAVE_ONLY_SUCCESS:
            success_results = [r for r in self.results if r.get('status') == 'success']
        else:
            success_results = self.results
        
        if not success_results:
            print("⚠️ Không có URL thành công để lưu!")
            return
        
        df = pd.DataFrame(success_results)
        df['scraped_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        dm = DataManager(OUTPUT_DIR)
        dm.print_summary(df)
        dm.save_to_csv(df)
        dm.save_to_json(df)
    
    def print_statistics(self):
        print("\n" + "=" * 70)
        print("📊 THỐNG KÊ TỔNG HỢP")
        print("=" * 70)
        
        total = len(self.results)
        success = len([r for r in self.results if r.get('status') == 'success'])
        failed = total - success
        
        print(f"📦 Tổng số URLs: {total}")
        print(f"✅ Thành công: {success}")
        print(f"❌ Thất bại: {failed}")
        
        if total > 0:
            print(f"📈 Tỷ lệ thành công: {(success/total)*100:.1f}%")
        
        print(f"\n🔄 Số lần retry (mỗi URL): {self.stats['retries']}")
        print(f"🔁 Số lần retry toàn bộ: {self.stats['final_retries']}")
        
        # Thống kê lỗi theo category
        error_categories = {}
        for result in self.results:
            if result.get('status') != 'success':
                error_detail = result.get('error_detail', {})
                category = error_detail.get('category', '❌ LỖI KHÁC')
                error_categories[category] = error_categories.get(category, 0) + 1
        
        if error_categories:
            print("\n📊 PHÂN TÍCH LỖI:")
            for category, count in sorted(error_categories.items(), key=lambda x: x[1], reverse=True):
                print(f"   {category}: {count} URLs")
    
    async def run(self):
        print("\n" + "=" * 70)
        print("🚀 AMAZON SCRAPER - ĐA LUỒNG + PHÂN TÍCH LỖI")
        print("=" * 70)
        print(f"⚡ Số luồng: {self.max_workers}")
        print(f"🔁 Retry mỗi URL: {MAX_RETRIES_PER_URL} lần (đổi proxy)")
        print(f"🔄 Retry toàn bộ URL thất bại: {MAX_FINAL_RETRY} lần")
        print("=" * 70)

        await self.proxy_manager.classify_proxies_by_country()
        
        urls = self.read_urls()
        if not urls:
            return
        
        results = self.scrape_batch(urls, 0)
        self.results = results
        
        self.failed_urls = [r for r in results if r.get('status') != 'success']
        
        if self.failed_urls:
            self.retry_failed_urls()
        
        self.save_results()
        self.print_statistics()
        
        print("\n✅ HOÀN TẤT!")

    async def verify_and_correct_proxy_country(self, proxy: Dict, url: str, result: Dict):
        """
        Kiểm tra quốc gia proxy khi crawl thất bại.
        Nếu proxy không đúng quốc gia yêu cầu, điều chỉnh vào đúng quốc gia thực.
        """
        target_country = self.get_country_from_url(url)
        proxy_host = proxy['host']
        
        # Lấy quốc gia thực của proxy (nếu chưa có trong cache)
        if proxy_host not in self.proxy_manager.proxy_country_cache:
            country = await self.proxy_manager._detect_proxy_country_smart(proxy)
        else:
            country = self.proxy_manager.proxy_country_cache.get(proxy_host, "Unknown")
        
        # Nếu proxy không đúng quốc gia yêu cầu
        if country != target_country and country != "Unknown":
            print(f"   🔄 PHÁT HIỆN SAI QUỐC GIA:")
            print(f"      Proxy {proxy_host} thực tế ở {country}, không phải {target_country}")
            print(f"      Đang điều chỉnh vào đúng quốc gia...")
            
            # Xóa proxy khỏi quốc gia cũ (nếu có)
            for old_country, proxies in self.proxy_manager.proxies_by_country.items():
                if any(p['host'] == proxy_host for p in proxies):
                    self.proxy_manager.proxies_by_country[old_country] = [
                        p for p in proxies if p['host'] != proxy_host
                    ]
                    break
            
            # Thêm proxy vào đúng quốc gia
            if country not in self.proxy_manager.proxies_by_country:
                self.proxy_manager.proxies_by_country[country] = []
            self.proxy_manager.proxies_by_country[country].append(proxy)
            
            # Cập nhật cache
            self.proxy_manager.proxy_country_cache[proxy_host] = country
            
            # Lưu lại
            self.proxy_manager._save_proxies_by_country()
            self.proxy_manager._save_country_cache()
            
            print(f"      ✅ Đã chuyển proxy vào danh sách {country}")
            return True
        return False

def main():
    import sys
    max_workers = MAX_WORKERS
    if len(sys.argv) > 1:
        try:
            max_workers = int(sys.argv[1])
            print(f"📝 Ghi đè số luồng: {max_workers}")
        except:
            pass
    
    scraper = HybridAmazonScraper(max_workers=max_workers)
    asyncio.run(scraper.run())

if __name__ == "__main__":
    main()