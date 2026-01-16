
import psycopg2
import psycopg2.extensions
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')

class CaseInsensitiveRecord(dict):
    """Mô phỏng row object của pyodbc/mssql: cho phép truy cập key bất kể hoa thường qua attribute hoặc key access."""
    def __getattr__(self, name):
        try:
            return self.__getitem__(name)
        except KeyError:
            raise AttributeError(f"Record has no attribute '{name}'")
    
    def __getitem__(self, key):
        if isinstance(key, int):
            # Lấy giá trị theo index nếu key là số nguyên
            return list(self.values())[key]
            
        if key in self:
            return super().__getitem__(key)
        
        if isinstance(key, str):
            lkey = key.lower()
            if lkey in self:
                return super().__getitem__(lkey)
            
            for k in self:
                if isinstance(k, str) and k.lower() == lkey:
                    return super().__getitem__(k)
        
        raise KeyError(key)

class CaseInsensitiveCursor(psycopg2.extensions.cursor):
    def _wrap_row(self, row):
        if row is None: return None
        # Tạo record từ mô tả cột và giá trị dòng
        return CaseInsensitiveRecord(zip([d[0] for d in self.description], row))

    def fetchone(self):
        return self._wrap_row(super().fetchone())

    def fetchall(self):
        rows = super().fetchall()
        return [self._wrap_row(r) for r in rows]

def debug_dashboard_logic():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=CaseInsensitiveCursor)
    cursor = conn.cursor()
    
    # Mimic admin_dashboard queries
    cursor.execute('SELECT * FROM vw_MonthlyRevenue ORDER BY Year DESC, Month DESC')
    monthly_revenue = cursor.fetchall()
    
    today = datetime.now()
    print(f"DEBUG: today={today}, year={today.year}, month={today.month}")
    
    current_month_revenue = 0
    current_month_orders = 0
    
    if monthly_revenue:
        print(f"DEBUG: First row keys: {list(monthly_revenue[0].keys())}")
        print(f"DEBUG: First row values: {monthly_revenue[0]}")
        
    for r in monthly_revenue:
        print(f"DEBUG: Checking row Year={r.Year} ({type(r.Year)}), Month={r.Month} ({type(r.Month)})")
        
        # Exact logic from admin.py
        try:
            r_year = int(r.Year)
            r_month = int(r.Month)
            
            if r_year == today.year and r_month == today.month:
                print("DEBUG: MATCH FOUND!")
                current_month_revenue = r.TotalRevenue
                current_month_orders = r.OrderCount
                break
            else:
                print(f"DEBUG: No match: {r_year}!={today.year} or {r_month}!={today.month}")
        except Exception as e:
            print(f"DEBUG: Error processing row: {e}")

    print(f"RESULT: Revenue={current_month_revenue}, Orders={current_month_orders}")
    conn.close()

if __name__ == "__main__":
    debug_dashboard_logic()
