# cookie_manager.py
import json
from pathlib import Path
from typing import Optional, Dict, List

class CookieManager:
    def __init__(self, cookie_dir: str = "cookies"):
        self.cookie_dir = Path(cookie_dir)
        self.cookie_dir.mkdir(exist_ok=True)
        self.cookies_cache: Dict[str, List[Dict]] = {}
    
    def get_cookie_for_country(self, country: str) -> Optional[str]:
        """Lấy cookie string cho quốc gia cụ thể"""
        cookie_file = self.cookie_dir / f"cookies_{country}.json"
        
        if not cookie_file.exists():
            print(f"⚠️ Chưa có cookie cho {country}. Chạy: ./run.sh cookie")
            return None
        
        # Đọc cache
        if country not in self.cookies_cache:
            with open(cookie_file, 'r') as f:
                self.cookies_cache[country] = json.load(f)
        
        cookies = self.cookies_cache[country]
        
        # Lấy cookie quan trọng
        important_names = ['session-id', 'ubid-main', 'x-main', 'lc-main']
        important_cookies = [c for c in cookies if c['name'] in important_names]
        
        if not important_cookies:
            important_cookies = cookies[:5]
        
        return '; '.join([f"{c['name']}={c['value']}" for c in important_cookies])
    
    def get_cookie_string(self, url: str = None) -> Optional[str]:
        """Lấy cookie string dựa trên URL (tự động phát hiện quốc gia)"""
        if not url:
            # Mặc định lấy cookie France
            return self.get_cookie_for_country("France")
        
        # Phát hiện quốc gia từ URL
        country_mapping = {
            'amazon.fr': 'France',
            'amazon.de': 'Germany',
            'amazon.co.uk': 'United Kingdom',
            'amazon.it': 'Italy',
            'amazon.es': 'Spain',
            'amazon.com': 'USA',
            'amazon.ca': 'Canada',
        }
        
        for domain, country in country_mapping.items():
            if domain in url.lower():
                return self.get_cookie_for_country(country)
        
        return self.get_cookie_for_country("France")