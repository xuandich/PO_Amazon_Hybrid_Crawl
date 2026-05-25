# proxy_manager.py - Kết hợp 3 phương pháp phát hiện quốc gia
import pandas as pd
import random
import json
import aiohttp
import asyncio
import ipaddress
from pathlib import Path
from typing import Dict, List, Optional, Set
from collections import defaultdict, Counter
from datetime import datetime

# Cấu hình mapping thủ công (có thể đặt trong config.py)
PROXY_COUNTRY_OVERRIDE = {
    '82.26.234.169': 'United Kingdom',  # IP này thực tế ở Anh
    '46.203.41.247': 'France',
    # Thêm các IP khác nếu biết trước
}

# Dải IP của Pháp (dựa trên RIPE NCC)
FRENCH_IP_RANGES = [
    "46.203.0.0/16",      # Orange France
    "82.26.0.0/16",       # BT (UK) - KHÔNG phải France, để test
    "193.252.0.0/16",     # Free SAS
    "194.158.0.0/16",     # Orange France
    "212.198.0.0/16",     # Free SAS
    "90.0.0.0/8",         # Orange France
    "109.0.0.0/12",       # Orange France
]

class ProxyManager:
    def __init__(self, proxy_file: str = None):
        self.proxy_file = proxy_file or "Proxy/buyproxies_List.xlsx"
        self.country_json_file = Path("Proxy/proxy_by_country.json")
        self.cache_json_file = Path("Proxy/proxy_country_cache.json")
        
        self.proxies: List[Dict] = []
        self.proxies_by_country: Dict[str, List[Dict]] = defaultdict(list)
        self.proxy_country_cache: Dict[str, str] = {}
        self.failed_proxies: Set[str] = set()
        self.current_index = 0
        self.rotation_strategy = "random"
        
        Path("Proxy").mkdir(exist_ok=True)
        
        self._load_country_cache()
        self._load_proxies()
        self._load_proxies_by_country()
    
    def _load_country_cache(self):
        """Đọc cache mapping ip -> country từ file JSON"""
        if self.cache_json_file.exists():
            try:
                with open(self.cache_json_file, 'r') as f:
                    self.proxy_country_cache = json.load(f)
                print(f"✅ Đã tải cache {len(self.proxy_country_cache)} proxies")
            except Exception as e:
                print(f"⚠️ Lỗi đọc cache: {e}")
    
    def _save_country_cache(self):
        """Lưu cache mapping ip -> country vào file JSON"""
        try:
            with open(self.cache_json_file, 'w') as f:
                json.dump(self.proxy_country_cache, f, indent=2)
            print(f"💾 Đã lưu cache {len(self.proxy_country_cache)} proxies")
        except Exception as e:
            print(f"⚠️ Lỗi lưu cache: {e}")
    
    def _load_proxies_by_country(self):
        """Đọc proxy đã phân loại theo quốc gia từ file JSON"""
        if self.country_json_file.exists():
            try:
                with open(self.country_json_file, 'r') as f:
                    data = json.load(f)
                    for country, proxies in data.items():
                        self.proxies_by_country[country] = proxies
                print(f"✅ Đã tải proxy theo quốc gia")
            except Exception as e:
                print(f"⚠️ Lỗi đọc proxy theo quốc gia: {e}")
    
    def _save_proxies_by_country(self):
        """Lưu proxy đã phân loại theo quốc gia vào file JSON"""
        try:
            data = {}
            for country, proxies in self.proxies_by_country.items():
                data[country] = proxies
            with open(self.country_json_file, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"💾 Đã lưu proxy theo quốc gia")
        except Exception as e:
            print(f"⚠️ Lỗi lưu proxy theo quốc gia: {e}")
    
    def _load_proxies(self):
        """Đọc danh sách proxy từ file Excel"""
        if not Path(self.proxy_file).exists():
            print(f"⚠️ Không tìm thấy file proxy: {self.proxy_file}")
            return
        
        print(f"📖 Đang đọc proxy từ: {self.proxy_file}")
        df = pd.read_excel(self.proxy_file, header=None)
        
        for _, row in df.iterrows():
            proxy_string = row[1] if len(row) > 1 else row[0]
            if isinstance(proxy_string, str) and proxy_string.strip():
                proxy_dict = self._parse_proxy_string(proxy_string)
                if proxy_dict:
                    self.proxies.append(proxy_dict)
        
        print(f"✅ Đã tải {len(self.proxies)} proxies")
    
    def get_unclassified_proxies(self) -> List[Dict]:
        """Lấy danh sách proxy chưa được phân loại quốc gia"""
        unclassified = []
        for proxy in self.proxies:
            if proxy['host'] not in self.proxy_country_cache:
                unclassified.append(proxy)
        return unclassified
    
    # ==================== PHƯƠNG PHÁP 1: IP RANGE CHECK ====================
    def _is_ip_in_french_range(self, ip: str) -> bool:
        """Kiểm tra IP có thuộc dải IP của Pháp không (dựa trên whois)"""
        try:
            ip_obj = ipaddress.ip_address(ip)
            for range_str in FRENCH_IP_RANGES:
                if ip_obj in ipaddress.ip_network(range_str, strict=False):
                    return True
        except Exception:
            pass
        return False
    
    def _is_ip_in_uk_range(self, ip: str) -> bool:
        """Kiểm tra IP có thuộc dải IP của Anh không"""
        uk_ranges = [
            "82.26.0.0/16",      # BT (British Telecom)
            "81.0.0.0/12",       # Various UK ISPs
            "90.0.0.0/9",        # Various UK ISPs
        ]
        try:
            ip_obj = ipaddress.ip_address(ip)
            for range_str in uk_ranges:
                if ip_obj in ipaddress.ip_network(range_str, strict=False):
                    return True
        except Exception:
            pass
        return False
    
    def _get_country_by_ip_range(self, ip: str) -> Optional[str]:
        """Phát hiện quốc gia qua IP range"""
        if self._is_ip_in_french_range(ip):
            return "France"
        if self._is_ip_in_uk_range(ip):
            return "United Kingdom"
        return None
    
    # ==================== PHƯƠNG PHÁP 2: MANUAL OVERRIDE ====================
    def _get_country_by_override(self, ip: str) -> Optional[str]:
        """Lấy quốc gia từ mapping thủ công"""
        return PROXY_COUNTRY_OVERRIDE.get(ip)
    
    # ==================== PHƯƠNG PHÁP 3: API CHECK ====================
    async def _get_country_by_api(self, proxy: Dict) -> str:
        """Phát hiện quốc gia qua API (chậm nhất)"""
        proxy_url = self._get_proxy_url(proxy)
        
        apis = [
            ("http://ip-api.com/json/", lambda d: d.get('country', 'Unknown')),
        ]
        
        for api_url, parser in apis:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(api_url, proxy=proxy_url, timeout=10) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get('status') == 'success':
                                country = parser(data)
                                if country != "Unknown":
                                    return country
            except Exception:
                continue
        return "Unknown"
    
    # ==================== PHƯƠNG PHÁP KẾT HỢP ====================
    async def _detect_proxy_country_smart(self, proxy: Dict) -> str:
        """
        PHÁT HIỆN QUỐC GIA THÔNG MINH - KẾT HỢP 3 PHƯƠNG PHÁP
        Ưu tiên: Manual Override → IP Range → API
        """
        host = proxy['host']
        
        # Kiểm tra cache
        if host in self.proxy_country_cache:
            return self.proxy_country_cache[host]
        
        # 1. MANUAL OVERRIDE (nhanh nhất, độ chính xác cao nhất)
        country = self._get_country_by_override(host)
        if country:
            print(f"   📌 {host} → {country} (manual override)")
            self.proxy_country_cache[host] = country
            return country
        
        # 2. IP RANGE CHECK (nhanh, không cần API)
        country = self._get_country_by_ip_range(host)
        if country:
            print(f"   🌐 {host} → {country} (IP range)")
            self.proxy_country_cache[host] = country
            return country
        
        # 3. API CHECK (chậm nhất, nhưng chính xác)
        print(f"   🔍 {host} → đang kiểm tra qua API...")
        country = await self._get_country_by_api(proxy)
        if country != "Unknown":
            print(f"   ✅ {host} → {country} (API)")
            self.proxy_country_cache[host] = country
            return country
        
        # Không xác định được
        print(f"   ⚠️ {host} → Unknown")
        self.proxy_country_cache[host] = "Unknown"
        return "Unknown"
    
    async def classify_proxies_by_country(self, max_concurrent: int = 10):
        """Phân loại proxy mới theo quốc gia (chỉ proxy chưa có)"""
        unclassified = self.get_unclassified_proxies()
        
        if not unclassified:
            print(f"\n✅ Tất cả {len(self.proxies)} proxies đã được phân loại")
            self._print_country_stats()
            return
        
        print(f"\n🌍 Đang phân loại {len(unclassified)} proxy mới theo quốc gia...")
        print("   Phương pháp: Manual Override → IP Range → API")
        print("-" * 60)
        
        # Phân loại song song
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def classify_one(proxy):
            async with semaphore:
                country = await self._detect_proxy_country_smart(proxy)
                if country != "Unknown":
                    self.proxies_by_country[country].append(proxy)
                return country
        
        tasks = [classify_one(proxy) for proxy in unclassified]
        await asyncio.gather(*tasks)
        
        # Lưu kết quả
        self._save_proxies_by_country()
        self._save_country_cache()
        
        self._print_country_stats()
    
    def _print_country_stats(self):
        """In thống kê proxy theo quốc gia"""
        print(f"\n📊 THỐNG KÊ PROXY THEO QUỐC GIA:")
        if not self.proxies_by_country:
            print("   Chưa có dữ liệu")
            return
        
        for country, proxies in sorted(self.proxies_by_country.items(), key=lambda x: len(x[1]), reverse=True):
            print(f"   - {country}: {len(proxies)} proxies")
    
    def get_proxy_by_country(self, target_country: str) -> Optional[Dict]:
        """Lấy proxy ngẫu nhiên từ quốc gia chỉ định"""
        if target_country not in self.proxies_by_country:
            return None
        
        available = [p for p in self.proxies_by_country[target_country] 
                    if p['host'] not in self.failed_proxies]
        
        if not available:
            return None
        
        if self.rotation_strategy == "random":
            return random.choice(available)
        else:
            proxy = available[self.current_index % len(available)]
            self.current_index += 1
            return proxy
    
    def get_next_proxy(self, target_country: str = None) -> Optional[Dict]:
        """Lấy proxy tiếp theo, ưu tiên đúng quốc gia"""
        if target_country:
            proxy = self.get_proxy_by_country(target_country)
            if proxy:
                return proxy
        
        # Fallback: lấy proxy bất kỳ
        available = [p for p in self.proxies if p['host'] not in self.failed_proxies]
        if not available:
            return None
        
        if self.rotation_strategy == "random":
            return random.choice(available)
        else:
            proxy = available[self.current_index % len(available)]
            self.current_index += 1
            return proxy
    
    def _get_proxy_url(self, proxy: Dict) -> str:
        if proxy.get('user') and proxy.get('pass'):
            return f"http://{proxy['user']}:{proxy['pass']}@{proxy['host']}:{proxy['port']}"
        return f"http://{proxy['host']}:{proxy['port']}"
    
    def _parse_proxy_string(self, proxy_string: str) -> Optional[Dict]:
        try:
            if '@' in proxy_string:
                auth_part, host_part = proxy_string.split('@')
                if ':' in auth_part:
                    user, pwd = auth_part.split(':', 1)
                else:
                    user, pwd = auth_part, ''
            else:
                user, pwd = '', ''
                host_part = proxy_string
            
            if ':' in host_part:
                host, port = host_part.split(':', 1)
            else:
                host, port = host_part, '80'
            
            return {'host': host, 'port': port, 'user': user, 'pass': pwd}
        except Exception:
            return None
    
    def mark_proxy_failed(self, proxy_host: str):
        self.failed_proxies.add(proxy_host)
    
    # Hàm kiểm tra lại một IP cụ thể
    async def recorrect_proxy_country(self, proxy_host: str):
        """Kiểm tra lại quốc gia của một proxy cụ thể"""
        for proxy in self.proxies:
            if proxy['host'] == proxy_host:
                print(f"\n🔄 Kiểm tra lại proxy {proxy_host}...")
                old_country = self.proxy_country_cache.get(proxy_host, "Unknown")
                
                # Xóa cache cũ
                if proxy_host in self.proxy_country_cache:
                    del self.proxy_country_cache[proxy_host]
                
                # Phát hiện lại
                new_country = await self._detect_proxy_country_smart(proxy)
                
                print(f"   Quốc gia cũ: {old_country} → Quốc gia mới: {new_country}")
                
                # Cập nhật lại danh sách theo quốc gia
                if old_country != "Unknown" and old_country in self.proxies_by_country:
                    self.proxies_by_country[old_country] = [
                        p for p in self.proxies_by_country[old_country] 
                        if p['host'] != proxy_host
                    ]
                
                if new_country != "Unknown":
                    self.proxies_by_country[new_country].append(proxy)
                
                # Lưu lại
                self._save_proxies_by_country()
                self._save_country_cache()
                return new_country
        return "Unknown"
    
    def get_proxy_country(self, proxy_host: str) -> Optional[str]:
        """Lấy quốc gia của proxy từ cache"""
        return self.proxy_country_cache.get(proxy_host)

    def update_proxy_country(self, proxy_host: str, new_country: str):
        """Cập nhật quốc gia cho proxy"""
        # Tìm proxy trong danh sách
        proxy = None
        for p in self.proxies:
            if p['host'] == proxy_host:
                proxy = p
                break
        
        if not proxy:
            return
        
        # Xóa khỏi quốc gia cũ
        for country, proxies in self.proxies_by_country.items():
            if any(p['host'] == proxy_host for p in proxies):
                self.proxies_by_country[country] = [
                    p for p in proxies if p['host'] != proxy_host
                ]
                break
        
        # Thêm vào quốc gia mới
        if new_country not in self.proxies_by_country:
            self.proxies_by_country[new_country] = []
        self.proxies_by_country[new_country].append(proxy)
        
        # Cập nhật cache
        self.proxy_country_cache[proxy_host] = new_country
        
        # Lưu lại
        self._save_proxies_by_country()
        self._save_country_cache()
        
        print(f"   ✅ Đã cập nhật proxy {proxy_host} → {new_country}")