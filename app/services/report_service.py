from app.services.base_service import BaseService
from datetime import datetime, timedelta
import json
import io
import csv

class ReportService(BaseService):
    @staticmethod
    def get_dashboard_stats():
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT * FROM vw_MonthlyRevenue ORDER BY Year DESC, Month DESC')
            monthly_revenue = cursor.fetchall()
            
            cursor.execute('SELECT * FROM vw_CategoryRevenue ORDER BY TotalRevenue DESC')
            category_revenue = cursor.fetchall()
            
            cursor.execute('SELECT * FROM vw_BestSellingProducts')
            best_selling = cursor.fetchall()
            
            today = datetime.now()
            current_month_revenue = 0
            current_month_orders = 0
            
            for r in monthly_revenue:
                try:
                    r_year = int(r.Year)
                    r_month = int(r.Month)
                    if r_year == today.year and r_month == today.month:
                        current_month_revenue = r.TotalRevenue
                        current_month_orders = r.OrderCount
                        break
                except (ValueError, TypeError, AttributeError):
                    continue
            
            total_sold = sum(p.TotalSold for p in best_selling)
            
            cursor.execute('SELECT COUNT(*) FROM Customers WHERE EXTRACT(YEAR FROM CreatedAt) = %s AND EXTRACT(MONTH FROM CreatedAt) = %s', (today.year, today.month))
            new_customers = cursor.fetchone()[0]
            
            return {
                'monthly_revenue': monthly_revenue,
                'category_revenue': category_revenue,
                'best_selling': best_selling,
                'current_month_revenue': current_month_revenue,
                'current_month_orders': current_month_orders,
                'total_sold': total_sold,
                'new_customers': new_customers
            }
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_revenue_report(start_date, end_date, group_by='day'):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            if not start_date:
                try:
                    cursor.execute("SELECT MIN(OrderDate) FROM Orders")
                    min_date_row = cursor.fetchone()
                    start_date = min_date_row[0].strftime('%Y-%m-%d') if min_date_row and min_date_row[0] else (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
                except:
                     start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

            if not end_date: end_date = datetime.now().strftime('%Y-%m-%d')

            # Always fetch daily data first
            cursor.execute('SELECT * FROM sp_GetRevenueByDateRange_Daily(%s, %s)', (start_date, end_date))
            daily_rows = cursor.fetchall()
            
            # Aggregate based on group_by
            aggregated_data = {} # Key: Date/Week/Month string, Value: {revenue, orders, date_obj}
            
            for row in daily_rows:
                if not row.OrderDate: continue
                
                date_key = ''
                display_date = row.OrderDate
                
                if group_by == 'week':
                    # ISO Week
                    year, week, _ = row.OrderDate.isocalendar()
                    date_key = f"{year}-W{week}"
                    # Use Monday of that week as display date
                    display_date = datetime.strptime(f'{year}-W{week}-1', "%Y-W%W-%w").date()
                elif group_by == 'month':
                    date_key = row.OrderDate.strftime('%Y-%m')
                    display_date = row.OrderDate.replace(day=1)
                elif group_by == 'year':
                    date_key = row.OrderDate.strftime('%Y')
                    display_date = row.OrderDate.replace(month=1, day=1)
                else: # day
                    date_key = row.OrderDate.strftime('%Y-%m-%d')
                
                if date_key not in aggregated_data:
                    aggregated_data[date_key] = {
                        'OrderDate': display_date,
                        'DailyRevenue': 0,
                        'OrderCount': 0
                    }
                
                aggregated_data[date_key]['DailyRevenue'] += (float(row.DailyRevenue) if row.DailyRevenue else 0)
                aggregated_data[date_key]['OrderCount'] += (row.OrderCount or 0)
            
            # Convert back to list and sort
            daily_revenue = []
            for key in sorted(aggregated_data.keys()):
                item = aggregated_data[key]
                # Mock object to match row interface if needed, or just dict
                # The template accesses .OrderDate, .DailyRevenue
                # Let's use a simple class or namedtuple, or just ensure template handles dicts?
                # The existing template uses dot notation (row.OrderDate). 
                # Let's return a list of objects that support dot notation.
                class ReportRow:
                    def __init__(self, data):
                        self.OrderDate = data['OrderDate']
                        self.DailyRevenue = data['DailyRevenue']
                        self.OrderCount = data['OrderCount']
                daily_revenue.append(ReportRow(item))

            cursor.execute('SELECT * FROM sp_GetRevenueByDateRange_Category(%s, %s)', (start_date, end_date))
            category_revenue = cursor.fetchall()
            
            cursor.execute('SELECT * FROM vw_BestSellingProducts')
            best_selling = cursor.fetchall()
            
            cursor.execute('SELECT COUNT(*) FROM Customers WHERE CAST(CreatedAt AS DATE) BETWEEN %s AND %s', (start_date, end_date))
            new_customers_range = cursor.fetchone()[0]
            
            return {
                'start_date': start_date,
                'end_date': end_date,
                'daily_revenue': daily_revenue,
                'category_revenue': category_revenue,
                'best_selling': best_selling,
                'new_customers_range': new_customers_range,
                'group_by': group_by
            }
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def generate_csv_report(report_type, start_date, end_date):
        conn = BaseService.get_connection()
        cursor = conn.cursor()
        try:
            output = io.StringIO()
            output.write('\ufeff')
            writer = csv.writer(output)
            
            if report_type == 'daily_revenue':
                cursor.execute('SELECT * FROM sp_GetRevenueByDateRange_Daily(%s, %s)', (start_date, end_date))
                rows = cursor.fetchall()
                writer.writerow(['Ngày', 'Số đơn hàng', 'Doanh thu (VNĐ)'])
                for row in rows:
                    date_str = row.OrderDate.strftime('%d/%m/%Y') if row.OrderDate else 'N/A'
                    writer.writerow([date_str, row.OrderCount, float(row.DailyRevenue) if row.DailyRevenue else 0])
                    
            elif report_type == 'best_selling':
                cursor.execute('''
                    SELECT p.ProductName, SUM(od.Quantity) as TotalSold, SUM(od.Quantity * od.Price) as Revenue
                    FROM OrderDetails od
                    JOIN ProductVariants pv ON od.VariantID = pv.VariantID
                    JOIN Products p ON pv.ProductID = p.ProductID
                    JOIN Orders o ON od.OrderID = o.OrderID
                    WHERE o.OrderDate BETWEEN %s AND %s
                    GROUP BY p.ProductID, p.ProductName
                    ORDER BY TotalSold DESC LIMIT 20
                ''', (start_date, end_date))
                rows = cursor.fetchall()
                writer.writerow(['Tên sản phẩm', 'Số lượng bán', 'Doanh thu (VNĐ)'])
                for row in rows:
                    writer.writerow([row[0], row[1], float(row[2]) if row[2] else 0])
                    
            elif report_type == 'category_revenue':
                cursor.execute('''
                    SELECT c.CategoryName, COUNT(DISTINCT o.OrderID) as OrderCount, SUM(od.Quantity * od.Price) as Revenue
                    FROM OrderDetails od
                    JOIN ProductVariants pv ON od.VariantID = pv.VariantID
                    JOIN Products p ON pv.ProductID = p.ProductID
                    JOIN Categories c ON p.CategoryID = c.CategoryID
                    JOIN Orders o ON od.OrderID = o.OrderID
                    WHERE o.OrderDate BETWEEN %s AND %s
                    GROUP BY c.CategoryID, c.CategoryName
                    ORDER BY Revenue DESC
                ''', (start_date, end_date))
                rows = cursor.fetchall()
                writer.writerow(['Danh mục', 'Số đơn hàng', 'Doanh thu (VNĐ)'])
                for row in rows:
                    writer.writerow([row[0], row[1], float(row[2]) if row[2] else 0])
                    
            elif report_type == 'top_customers':
                cursor.execute('''
                    SELECT c.FullName, c.Email, COUNT(o.OrderID) as OrderCount, SUM(o.TotalAmount) as TotalSpent
                    FROM Customers c
                    JOIN Orders o ON c.CustomerID = o.CustomerID
                    WHERE o.OrderDate BETWEEN %s AND %s
                    GROUP BY c.CustomerID, c.FullName, c.Email
                    ORDER BY TotalSpent DESC LIMIT 20
                ''', (start_date, end_date))
                rows = cursor.fetchall()
                writer.writerow(['Tên khách hàng', 'Email', 'Số đơn hàng', 'Tổng chi tiêu (VNĐ)'])
                for row in rows:
                    writer.writerow([row[0], row[1], row[2], float(row[3]) if row[3] else 0])

            elif report_type == 'low_stock':
                cursor.execute('''
                    SELECT p.ProductName, c.ColorName, s.SizeName, pv.Quantity
                    FROM ProductVariants pv
                    JOIN Products p ON pv.ProductID = p.ProductID
                    JOIN Colors c ON pv.ColorID = c.ColorID
                    JOIN Sizes s ON pv.SizeID = s.SizeID
                    WHERE pv.Quantity < 20
                    ORDER BY pv.Quantity ASC LIMIT 50
                ''')
                rows = cursor.fetchall()
                writer.writerow(['Sản phẩm', 'Màu', 'Size', 'Số lượng còn'])
                for row in rows:
                    writer.writerow([row[0], row[1], row[2], row[3]])
                    
            elif report_type == 'order_details':
                cursor.execute('''
                    SELECT o.OrderID, c.FullName, o.OrderDate, o.TotalAmount, o.Status, o.PaymentMethod
                    FROM Orders o
                    JOIN Customers c ON o.CustomerID = c.CustomerID
                    WHERE o.OrderDate BETWEEN %s AND %s
                    ORDER BY o.OrderDate DESC LIMIT 100
                ''', (start_date, end_date))
                rows = cursor.fetchall()
                writer.writerow(['Mã đơn', 'Khách hàng', 'Ngày đặt', 'Tổng tiền (VNĐ)', 'Trạng thái', 'Thanh toán'])
                for row in rows:
                    date_str = row[2].strftime('%d/%m/%Y %H:%M') if row[2] else 'N/A'
                    writer.writerow([row[0], row[1], date_str, float(row[3]) if row[3] else 0, row[4], row[5] or 'N/A'])
            
            return output.getvalue().encode('utf-8-sig')
        finally:
            cursor.close()
            conn.close()
