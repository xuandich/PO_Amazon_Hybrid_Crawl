# cookie_fetcher.py - Lấy cookie với proxy theo quốc gia
import asyncio
import json
import random
from pathlib import Path
from typing import Dict, List, Optional
from playwright.async_api import async_playwright
from proxy_manager import ProxyManager

class CookieFetcher:
    def __init__(self):
        self.cookie_dir = Path("cookies")
        self.cookie_dir.mkdir(exist_ok=True)
        self.proxy_manager = ProxyManager()
    
    def get_country_from_url(self, url: str) -> str:
        """Lấy quốc gia từ domain của URL Amazon"""
        country_mapping = {
            'amazon.fr': 'France',
            'amazon.de': 'Germany',
            'amazon.co.uk': 'United Kingdom',
            'amazon.it': 'Italy',
            'amazon.es': 'Spain',
            'amazon.nl': 'Netherlands',
            'amazon.se': 'Sweden',
            'amazon.pl': 'Poland',
            'amazon.be': 'Belgium',
            'amazon.com': 'USA',
            'amazon.ca': 'Canada',
            'amazon.com.mx': 'Mexico',
            'amazon.com.br': 'Brazil',
            'amazon.com.au': 'Australia',
            'amazon.in': 'India',
            'amazon.co.jp': 'Japan',
        }
        for domain, country in country_mapping.items():
            if domain in url.lower():
                return country
        return "Unknown"
    
    def get_urls_by_country(self, urls: List[str]) -> Dict[str, str]:
        """Phân loại URLs theo quốc gia, mỗi quốc gia lấy URL đầu tiên"""
        country_urls = {}
        for url in urls:
            country = self.get_country_from_url(url)
            if country not in country_urls:
                country_urls[country] = url
        return country_urls
    
    def get_proxy_for_country(self, country: str) -> Optional[Dict]:
        """Lấy proxy phù hợp với quốc gia"""
        # Lấy tất cả proxy
        all_proxies = self.proxy_manager.proxies
        
        # TODO: Nếu có thông tin quốc gia của proxy, có thể lọc chính xác hơn
        # Hiện tại lấy random từ danh sách proxy
        if all_proxies:
            return random.choice(all_proxies)
        return None
    
    async def fetch_cookies_with_proxy(self, url: str, proxy: Dict, country: str) -> bool:
        """
        Lấy cookie cho một URL với proxy cụ thể
        
        Args:
            url: URL cần lấy cookie
            proxy: Dict chứa thông tin proxy
            country: Tên quốc gia
        
        Returns:
            True nếu thành công, False nếu thất bại
        """
        print(f"\n🌍 Đang lấy cookie cho {country}")
        print(f"   🔗 URL: {url[:80]}...")
        print(f"   🔒 Proxy: {proxy['host']}:{proxy['port']}")
        if proxy.get('user'):
            print(f"   🔐 User: {proxy['user']}")
        
        try:
            async with async_playwright() as p:
                # Cấu hình proxy
                proxy_config = {
                    "server": f"http://{proxy['host']}:{proxy['port']}"
                }
                if proxy.get('user') and proxy.get('pass'):
                    proxy_config["username"] = proxy['user']
                    proxy_config["password"] = proxy['pass']
                
                # Khởi tạo browser với proxy
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-blink-features=AutomationControlled']
                )
                
                # Tạo context với proxy
                context = await browser.new_context(
                    proxy=proxy_config,
                    viewport={'width': 1280, 'height': 720},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
                )
                
                page = await context.new_page()
                
                # Truy cập URL
                print(f"   🌐 Đang truy cập...")
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                
                # Đợi cookie được set
                await asyncio.sleep(3)
                
                # Lấy cookies
                cookies = await context.cookies()
                
                # Lưu cookie riêng cho quốc gia
                cookie_file = self.cookie_dir / f"cookies_{country}.json"
                with open(cookie_file, 'w') as f:
                    json.dump(cookies, f, indent=2)
                
                # Lưu cookie string
                cookie_string = '; '.join([f"{c['name']}={c['value']}" for c in cookies if c['name'] in ['session-id', 'ubid-main', 'x-main']])
                cookie_str_file = self.cookie_dir / f"cookie_string_{country}.txt"
                with open(cookie_str_file, 'w') as f:
                    f.write(cookie_string)
                
                print(f"   ✅ Đã lấy {len(cookies)} cookies cho {country}")
                print(f"   📁 Lưu tại: {cookie_file}")
                
                await browser.close()
                return True
                
        except Exception as e:
            print(f"   ❌ Lỗi khi lấy cookie cho {country}: {e}")
            return False
    
    async def fetch_all_cookies(self, input_file: str = "input/amazon_FR.xlsx"):
        """Lấy cookie cho tất cả các quốc gia có trong file input"""
        import pandas as pd
        
        # Đọc URLs từ file input
        if not Path(input_file).exists():
            print(f"❌ Không tìm thấy file: {input_file}")
            return
        
        df = pd.read_excel(input_file, header=None)
        urls = [row[0] for _, row in df.iterrows() if isinstance(row[0], str) and row[0].startswith('http')]
        
        print(f"\n📖 Đã đọc {len(urls)} URLs từ {input_file}")
        
        # Lấy danh sách quốc gia duy nhất
        country_urls = self.get_urls_by_country(urls)
        
        print(f"\n🌍 PHÂN LOẠI THEO QUỐC GIA:")
        for country, url in country_urls.items():
            print(f"   - {country}: {url[:60]}...")
        
        print(f"\n🚀 BẮT ĐẦU LẤY COOKIE CHO {len(country_urls)} QUỐC GIA")
        print("=" * 70)
        
        # Lấy cookie cho từng quốc gia
        success_count = 0
        for country, url in country_urls.items():
            # Lấy proxy phù hợp
            proxy = self.get_proxy_for_country(country)
            
            if not proxy:
                print(f"\n⚠️ Không có proxy cho {country}, bỏ qua...")
                continue
            
            # Lấy cookie
            if await self.fetch_cookies_with_proxy(url, proxy, country):
                success_count += 1
            
            # Delay giữa các lần lấy cookie
            await asyncio.sleep(2)
        
        print(f"\n" + "=" * 70)
        print(f"✅ HOÀN TẤT: Đã lấy cookie thành công cho {success_count}/{len(country_urls)} quốc gia")
        print(f"📁 Cookie được lưu trong thư mục: cookies/")
        print("   - cookies_France.json")
        print("   - cookies_Germany.json")
        print("   - ...")

async def main():
    fetcher = CookieFetcher()
    await fetcher.fetch_all_cookies()

if __name__ == "__main__":
    asyncio.run(main())