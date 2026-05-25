# data_manager.py
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime
import os

class DataManager:
    def __init__(self, save_dir: str = "output"):
        self.save_dir = save_dir
        os.makedirs(self.save_dir, exist_ok=True)
    
    def save_to_csv(self, df: pd.DataFrame, filename: Optional[str] = None) -> str:
        if df.empty:
            return None
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"amazon_products_{timestamp}.csv"
        filepath = os.path.join(self.save_dir, filename)
        df.to_csv(filepath, index=False, encoding='utf-8-sig')
        print(f"✅ Đã lưu CSV: {filepath}")
        return filepath
    
    def save_to_json(self, df: pd.DataFrame, filename: Optional[str] = None) -> str:
        if df.empty:
            return None
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"amazon_products_{timestamp}.json"
        filepath = os.path.join(self.save_dir, filename)
        df.to_json(filepath, orient='records', force_ascii=False, indent=2)
        print(f"✅ Đã lưu JSON: {filepath}")
        return filepath
    
    def print_summary(self, df: pd.DataFrame):
        if df.empty:
            print("⚠️ Không có dữ liệu")
            return
        print(f"\n📊 Tổng số: {len(df)} URLs")
        print(f"✅ Thành công: {len(df[df['status'] == 'success'])}")