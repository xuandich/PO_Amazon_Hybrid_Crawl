# http_scraper.py
import random
import re
from typing import Dict, Optional
from bs4 import BeautifulSoup
from curl_cffi import requests

try:
    from config import CURL_IMPRERSONATE, REQUEST_TIMEOUT, MIN_DELAY, MAX_DELAY
except ImportError:
    CURL_IMPRERSONATE = "chrome120"
    REQUEST_TIMEOUT = 30
    MIN_DELAY = 1
    MAX_DELAY = 3

def get_product_info(url: str, cookie_string: str, proxy: Dict = None) -> Dict:
    """Lấy thông tin sản phẩm với cookie và proxy"""
    
    # Random delay
    delay = random.uniform(MIN_DELAY, MAX_DELAY)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
        'Cookie': cookie_string,
    }
    
    proxies = None
    if proxy:
        if proxy['user'] and proxy['pass']:
            proxy_url = f"http://{proxy['user']}:{proxy['pass']}@{proxy['host']}:{proxy['port']}"
        else:
            proxy_url = f"http://{proxy['host']}:{proxy['port']}"
        proxies = {"http": proxy_url, "https": proxy_url}
    
    try:
        response = requests.get(
            url,
            impersonate=CURL_IMPRERSONATE,
            headers=headers,
            proxies=proxies,
            timeout=REQUEST_TIMEOUT
        )
        
        if response.status_code != 200:
            return {"url": url, "status": f"http_{response.status_code}"}
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        title = soup.select_one('#btAsinTitle') or soup.select_one('#productTitle')
        title = title.get_text(strip=True) if title else None
        
        # PHẦN PRICE MỚI - Dựa trên XPath:
        # //*[@id="corePrice_desktop"]//*[contains(@class,"a-price a-text-price a-size-medium") and @data-a-color="price"]/span[1]
        # | //*[@id="apex_desktop"]//span[contains(@class,"priceToPay")]/span[1]
        
        price = None
        
        # Option 1: corePrice_desktop
        price_elem = soup.select_one('#corePrice_desktop .a-price.a-text-price.a-size-medium[data-a-color="price"] > span:first-child')
        
        if not price_elem:
            # Option 2: apex_desktop
            price_elem = soup.select_one('#apex_desktop span[class*="priceToPay"] > span:first-child')
        
        if price_elem:
            price = price_elem.get_text(strip=True)
        else:
            # Fallback: giữ lại logic cũ nếu không tìm thấy theo cách mới
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
        
        return {
            "url": url,
            "title": title,
            "price": price,
            "status": "success" if (title and price) else "missing_data"
        }
        
    except Exception as e:
        return {"url": url, "status": f"error: {str(e)[:50]}"}