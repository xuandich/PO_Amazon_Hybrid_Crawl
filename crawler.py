# crawler.py - Class Crawler chuyên xử lý scrape
import random
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from cookie_manager import CookieManager
from proxy_manager import ProxyManager
from data_manager import DataManager

try:
    from config import (
        MIN_DELAY, MAX_DELAY, REQUEST_TIMEOUT, CURL_IMPRERSONATE,
        MAX_RETRIES_PER_URL, RETRY_DELAY, RETRY_ON_ERRORS,
        MAX_WORKERS, SAVE_ONLY_SUCCESS, OUTPUT_DIR
    )
except ImportError:
    MIN_DELAY = 1
    MAX_DELAY = 3
    REQUEST_TIMEOUT = 30
    CURL_IMPRERSONATE = "chrome120"
    MAX_RETRIES_PER_URL = 3
    RETRY_DELAY = 2
    RETRY_ON_ERRORS = ["timeout", "connection", "http_403", "http_429", "http_503", "proxy_error", "missing_data"]
    MAX_WORKERS = 10
    SAVE_ONLY_SUCCESS = True
    OUTPUT_DIR = "output"

try:
    from curl_cffi import requests
    CURL_AVAILABLE = True
except ImportError:
    CURL_AVAILABLE = False
    import requests

# Thread local cho proxy manager
thread_local = threading.local()

def get_thread_proxy_manager():
    if not hasattr(thread_local, 'proxy_manager'):
        thread_local.proxy_manager = ProxyManager()
    return thread_local.proxy_manager


class AmazonCrawler:
    """Class chuyên xử lý crawl dữ liệu Amazon"""
    
    def __init__(self, max_workers: int = MAX_WORKERS):
        self.cookie_manager = CookieManager()
        self.max_workers = max_workers
        self.results: List[Dict] = []
        self.failed_urls: List[Dict] = []
        self.is_running = True
        self.lock = threading.Lock()
        self.stats = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'retries': 0,
            'final_retries': 0,
            'wrong_country': 0
        }
    
    def get_country_from_url(self, url: str) -> str:
        """Lấy quốc gia từ domain của URL Amazon"""
        country_mapping = {
            'amazon.fr': 'France',
            'amazon.de': 'Germany',
            'amazon.co.uk': 'United Kingdom',
            'amazon.it': 'Italy',
            'amazon.es': 'Spain',
            'amazon.nl': 'Netherlands',
            'amazon.com': 'USA',
            'amazon.ca': 'Canada',
            'amazon.com.au': 'Australia',
        }
        for domain, country in country_mapping.items():
            if domain in url.lower():
                return country
        return "Unknown"
    
    def check_country_from_xpath(self, html: str) -> str:
        """Kiểm tra quốc gia từ XPath global-location"""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        
        elements = soup.select('a[id*="global-location"] div span:nth-of-type(2)')
        if not elements:
            elements = soup.select('span#glow-ingress-line2, span.a-text-bold')
        
        for elem in elements:
            country_text = elem.get_text(strip=True)
            if country_text and len(country_text) > 2:
                print(f"   🏷️ XPath phát hiện quốc gia: {country_text}")
                return country_text
        return None
    
    def verify_country_match(self, url: str, html: str) -> tuple:
        """Xác minh quốc gia có khớp không"""
        expected_country = self.get_country_from_url(url)
        actual_country = self.check_country_from_xpath(html)
        
        if not actual_country:
            return True, expected_country, actual_country
        
        expected_lower = expected_country.lower()
        actual_lower = actual_country.lower()
        
        country_aliases = {
            'france': ['france', 'fr', 'frankreich', 'frankrike', 'la france', 'french'],
            'germany': ['germany', 'de', 'deutschland', 'allemagne', 'german'],
            'united kingdom': ['united kingdom', 'uk', 'england', 'great britain', 'royaume-uni', 'britain'],
            'usa': ['usa', 'us', 'united states', 'america', 'états-unis', 'americain'],
            'italy': ['italy', 'it', 'italia', 'italie', 'italiano'],
            'spain': ['spain', 'es', 'espana', 'espagne', 'espanol'],
            'canada': ['canada', 'ca'],
            'australia': ['australia', 'au'],
            'japan': ['japan', 'jp', 'japon'],
            'brazil': ['brazil', 'br', 'brasil'],
            'mexico': ['mexico', 'mx', 'mejico'],
        }
        
        for official, aliases in country_aliases.items():
            if expected_lower in aliases or official in expected_lower:
                if actual_lower in aliases or official in actual_lower:
                    return True, expected_country, actual_country
        
        if expected_lower == actual_lower:
            return True, expected_country, actual_country
        
        return False, expected_country, actual_country
    
    def get_product_info(self, url: str, cookie_string: str, proxy: Dict = None) -> Dict:
        """Lấy thông tin sản phẩm từ URL"""
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
            
            # Kiểm tra quốc gia
            country_matched, expected, actual = self.verify_country_match(url, response.text)
            
            result = {
                "url": url,
                "title": title,
                "price": price,
                "status": "success" if (title and price) else "missing_data",
                "country_expected": expected,
                "country_detected": actual,
                "country_matched": country_matched
            }
            
            if not country_matched and actual:
                print(f"   ⚠️ CẢNH BÁO: Nội dung là {actual}, không phải {expected}!")
                result['status'] = "wrong_country"
            
            return result
            
        except Exception as e:
            return {"url": url, "title": None, "price": None, "status": "error"}
    
    def scrape_single_url(self, url: str, idx: int, total: int, cookie_string: str, retry_round: int = 0) -> Dict:
        """Scrape một URL"""
        target_country = self.get_country_from_url(url)
        proxy_manager = get_thread_proxy_manager()
        
        print(f"\n{'─' * 70}")
        print(f"📦 [{idx}/{total}] {url[:80]}...")
        print(f"   🌍 Quốc gia mục tiêu: {target_country}")
        
        for attempt in range(1, MAX_RETRIES_PER_URL + 1):
            if not self.is_running:
                return None
            
            proxy = proxy_manager.get_next_proxy(target_country)
            
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
                result['proxy'] = proxy['host'] if proxy else None
                result['retries'] = attempt - 1
                result['retry_round'] = retry_round
                with self.lock:
                    self.stats['success'] += 1
                print(f"   ✅ THÀNH CÔNG: {result['title'][:50]}... - {result['price']}€")
                return result
            
            # Xử lý lỗi sai quốc gia
            if result['status'] == 'wrong_country':
                print(f"   ❌ SAI QUỐC GIA: mong đợi {result.get('country_expected')}, thực tế {result.get('country_detected')}")
                with self.lock:
                    self.stats['wrong_country'] += 1
            
            # Phân loại lỗi
            if 'timeout' in result['status']:
                print(f"   ❌ TIMEOUT")
            elif 'http_403' in result['status']:
                print(f"   ❌ BỊ CHẶN (403)")
            elif 'missing_data' in result['status']:
                print(f"   ❌ THIẾU DỮ LIỆU")
            else:
                print(f"   ❌ {result['status']}")
            
            if attempt < MAX_RETRIES_PER_URL:
                print(f"   🔄 Thử lại sau {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)
            else:
                result['proxy'] = proxy['host'] if proxy else None
                result['retries'] = attempt - 1
                with self.lock:
                    self.stats['failed'] += 1
                return result
        
        return {"url": url, "title": None, "price": None, "status": "failed"}
    
    def scrape_batch(self, urls: List[str], retry_round: int = 0) -> List[Dict]:
        """Scrape batch URLs với đa luồng"""
        cookie_string = self.cookie_manager.get_cookie_string()
        if not cookie_string:
            print("❌ Chưa có cookie! Chạy ./run.sh cookie")
            return []
        
        round_name = "RETRY" if retry_round > 0 else "LẦN ĐẦU"
        print(f"\n🚀 {round_name}: {len(urls)} URLs với {self.max_workers} luồng")
        print("=" * 70)
        
        results = []
        completed = 0
        total = len(urls)
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self.scrape_single_url, url, idx, total, cookie_string, retry_round): url
                for idx, url in enumerate(urls, 1)
            }
            
            for future in as_completed(futures):
                completed += 1
                try:
                    result = future.result()
                    if result:
                        results.append(result)
                except Exception as e:
                    print(f"❌ Lỗi: {e}")
                
                if completed % 10 == 0 or completed == total:
                    percent = (completed / total) * 100
                    print(f"\n📊 TIẾN ĐỘ: {completed}/{total} ({percent:.1f}%) | ✅ {self.stats['success']} | ❌ {self.stats['failed']}")
        
        return results
    
    def save_results(self):
        """Lưu kết quả"""
        if not self.results:
            return
        
        if SAVE_ONLY_SUCCESS:
            success_results = [r for r in self.results if r.get('status') == 'success']
        else:
            success_results = self.results
        
        if not success_results:
            return
        
        import pandas as pd
        df = pd.DataFrame(success_results)
        dm = DataManager(OUTPUT_DIR)
        dm.print_summary(df)
        dm.save_to_csv(df)
        dm.save_to_json(df)
    
    def print_stats(self):
        """In thống kê"""
        print("\n" + "=" * 70)
        print("📊 THỐNG KÊ")
        print("=" * 70)
        print(f"📦 Tổng: {len(self.results)}")
        print(f"✅ Thành công: {self.stats['success']}")
        print(f"❌ Thất bại: {self.stats['failed']}")
        print(f"🌍 Sai quốc gia: {self.stats['wrong_country']}")
        print(f"🔄 Số lần retry: {self.stats['retries']}")
        if len(self.results) > 0:
            print(f"📈 Tỷ lệ: {(self.stats['success']/len(self.results))*100:.1f}%")
    
    def run(self, urls: List[str]):
        """Chạy crawl"""
        self.results = self.scrape_batch(urls, 0)
        self.failed_urls = [r for r in self.results if r.get('status') != 'success']
        self.save_results()
        self.print_stats()