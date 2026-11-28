import csv
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.services.base_service import BaseService
from app.validation import ValidationError, date_value


# Vietnam observes UTC+07 year-round. This also works on hosts without an IANA database.
VIETNAM_TIME = timezone(timedelta(hours=7), 'Asia/Ho_Chi_Minh')


class ReportService(BaseService):
    """Realized revenue is the value of Delivered orders, by order date."""

    REPORT_NAMES = {
        'daily_revenue': 'Doanh thu đã giao theo thời gian',
        'best_selling': 'Sản phẩm đã giao bán chạy',
        'category_revenue': 'Doanh thu sản phẩm đã giao theo danh mục',
        'top_customers': 'Chi tiêu từ đơn đã giao của khách hàng',
        'low_stock': 'Tồn kho thấp hiện tại (không lọc theo ngày)',
        'order_details': 'Chi tiết đơn đã giao',
    }
    GROUPS = {'day', 'week', 'month', 'year'}

    @staticmethod
    def validate_dates(start_date, end_date):
        """Validate calendar dates before opening a connection."""
        start = date_value(start_date, 'Ngày bắt đầu') if start_date else None
        end = date_value(end_date, 'Ngày kết thúc') if end_date else datetime.now(VIETNAM_TIME).date()
        if end == date.max or (start is not None and start > end):
            raise ValidationError('Khoảng ngày không hợp lệ')
        return start, end

    @staticmethod
    def validate_report_type(report_type):
        if not isinstance(report_type, str) or report_type not in ReportService.REPORT_NAMES:
            raise ValidationError('Loại báo cáo không hợp lệ')
        return report_type

    @staticmethod
    def validate_group(group_by):
        if not isinstance(group_by, str) or group_by not in ReportService.GROUPS:
            raise ValidationError('Cách nhóm báo cáo không hợp lệ')
        return group_by

    @staticmethod
    def _resolve_dates(cursor, start, end):
        if start is None:
            cursor.execute("SELECT MIN(CAST(OrderDate AS DATE)) FROM Orders WHERE Status = 'Delivered'")
            row = cursor.fetchone()
            earliest = row[0] if row else None
            if isinstance(earliest, datetime):
                earliest = earliest.date()
            # An end date before the first order is a valid empty report.
            fallback = date.fromordinal(max(date.min.toordinal(), end.toordinal() - 365))
            start = min(earliest, end) if earliest else fallback
        return start, end + timedelta(days=1)

    @staticmethod
    def _daily_revenue(cursor, start, end_exclusive):
        cursor.execute(
            """
            SELECT CAST(o.OrderDate AS DATE) AS OrderDate,
                   COALESCE(SUM(o.TotalAmount), 0) AS DailyRevenue,
                   COUNT(*) AS OrderCount
            FROM Orders o
            WHERE o.Status = 'Delivered' AND o.OrderDate >= %s AND o.OrderDate < %s
            GROUP BY CAST(o.OrderDate AS DATE)
            ORDER BY OrderDate
        """,
            (start, end_exclusive),
        )
        return cursor.fetchall()

    @staticmethod
    def _category_revenue(cursor, start, end_exclusive):
        cursor.execute(
            """
            SELECT c.CategoryID, c.CategoryName,
                   COUNT(DISTINCT o.OrderID) AS OrderCount,
                   COALESCE(SUM(od.Quantity * od.Price), 0) AS CategoryRevenue
            FROM Orders o
            JOIN OrderDetails od ON od.OrderID = o.OrderID
            JOIN ProductVariants pv ON pv.VariantID = od.VariantID
            JOIN Products p ON p.ProductID = pv.ProductID
            JOIN Categories c ON c.CategoryID = p.CategoryID
            WHERE o.Status = 'Delivered' AND o.OrderDate >= %s AND o.OrderDate < %s
            GROUP BY c.CategoryID, c.CategoryName
            ORDER BY CategoryRevenue DESC, c.CategoryID
        """,
            (start, end_exclusive),
        )
        return cursor.fetchall()

    @staticmethod
    def _best_selling(cursor, start, end_exclusive):
        cursor.execute(
            """
            SELECT p.ProductID, p.ProductName, c.CategoryName,
                   SUM(od.Quantity) AS TotalSold,
                   COALESCE(SUM(od.Quantity * od.Price), 0) AS TotalRevenue
            FROM Orders o
            JOIN OrderDetails od ON od.OrderID = o.OrderID
            JOIN ProductVariants pv ON pv.VariantID = od.VariantID
            JOIN Products p ON p.ProductID = pv.ProductID
            JOIN Categories c ON c.CategoryID = p.CategoryID
            WHERE o.Status = 'Delivered' AND o.OrderDate >= %s AND o.OrderDate < %s
            GROUP BY p.ProductID, p.ProductName, c.CategoryName
            ORDER BY TotalSold DESC, p.ProductID
            LIMIT 20
        """,
            (start, end_exclusive),
        )
        return cursor.fetchall()

    @staticmethod
    def _group_revenue(rows, group_by):
        grouped = {}
        for row in rows:
            order_date = row.OrderDate
            if isinstance(order_date, datetime):
                order_date = order_date.date()
            if not order_date:
                continue
            if group_by == 'week':
                period = order_date - timedelta(days=order_date.weekday())
            elif group_by == 'month':
                period = order_date.replace(day=1)
            elif group_by == 'year':
                period = order_date.replace(month=1, day=1)
            else:
                period = order_date
            bucket = grouped.setdefault(period, {'revenue': Decimal('0'), 'orders': 0})
            bucket['revenue'] += Decimal(str(row.DailyRevenue or 0))
            bucket['orders'] += int(row.OrderCount or 0)
        return [
            SimpleNamespace(OrderDate=period, DailyRevenue=values['revenue'], OrderCount=values['orders'])
            for period, values in sorted(grouped.items())
        ]

    @staticmethod
    def get_dashboard_stats():
        """Dashboard history ends today; monthly cards refer to this month only."""
        today = datetime.now(VIETNAM_TIME).date()
        conn = ReportService.get_connection()
        try:
            with conn.cursor() as cursor:
                start, end_exclusive = ReportService._resolve_dates(cursor, None, today)
                monthly = ReportService._group_revenue(
                    ReportService._daily_revenue(cursor, start, end_exclusive), 'month'
                )
                monthly_revenue = [
                    SimpleNamespace(
                        Year=row.OrderDate.year,
                        Month=row.OrderDate.month,
                        TotalRevenue=row.DailyRevenue,
                        OrderCount=row.OrderCount,
                    )
                    for row in reversed(monthly)
                ]
                current = next(
                    (row for row in monthly_revenue if row.Year == today.year and row.Month == today.month), None
                )
                category_revenue = ReportService._category_revenue(cursor, start, end_exclusive)
                best_selling = ReportService._best_selling(cursor, start, end_exclusive)
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(od.Quantity), 0)
                    FROM Orders o JOIN OrderDetails od ON od.OrderID = o.OrderID
                    WHERE o.Status = 'Delivered' AND o.OrderDate >= %s AND o.OrderDate < %s
                """,
                    (start, end_exclusive),
                )
                total_sold = cursor.fetchone()[0]
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM Customers
                    WHERE CreatedAt >= %s AND CreatedAt < %s AND IsAdmin = FALSE
                """,
                    (today.replace(day=1), end_exclusive),
                )
                new_customers = cursor.fetchone()[0]
                return {
                    'monthly_revenue': monthly_revenue,
                    'category_revenue': category_revenue,
                    'best_selling': best_selling,
                    'current_month_revenue': current.TotalRevenue if current else Decimal('0'),
                    'current_month_orders': current.OrderCount if current else 0,
                    'total_sold': total_sold,
                    'new_customers': new_customers,
                    'history_start_date': start.isoformat(),
                    'history_end_date': today.isoformat(),
                }
        finally:
            conn.close()

    @staticmethod
    def get_revenue_report(start_date, end_date, group_by='day'):
        group_by = ReportService.validate_group(group_by)
        start, end = ReportService.validate_dates(start_date, end_date)
        conn = ReportService.get_connection()
        try:
            with conn.cursor() as cursor:
                start, end_exclusive = ReportService._resolve_dates(cursor, start, end)
                daily_revenue = ReportService._group_revenue(
                    ReportService._daily_revenue(cursor, start, end_exclusive), group_by
                )
                category_revenue = ReportService._category_revenue(cursor, start, end_exclusive)
                best_selling = ReportService._best_selling(cursor, start, end_exclusive)
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM Customers
                    WHERE CreatedAt >= %s AND CreatedAt < %s AND IsAdmin = FALSE
                """,
                    (start, end_exclusive),
                )
                new_customers = cursor.fetchone()[0]
                return {
                    'start_date': start.isoformat(),
                    'end_date': end.isoformat(),
                    'daily_revenue': daily_revenue,
                    'category_revenue': category_revenue,
                    'best_selling': best_selling,
                    'new_customers_range': new_customers,
                    'group_by': group_by,
                }
        finally:
            conn.close()

    @staticmethod
    def _csv_cell(value):
        if isinstance(value, str):
            candidate = value.lstrip(' \t\r\n\v\f\ufeff')
            if value.startswith(('\t', '\r', '\n')) or candidate.startswith(('=', '+', '-', '@')):
                return "'" + value
        return value

    @staticmethod
    def generate_csv_report(report_type, start_date, end_date, group_by='day'):
        """CSV amounts retain decimal precision and text cannot start formulas."""
        ReportService.validate_report_type(report_type)
        ReportService.validate_group(group_by)
        start, end = ReportService.validate_dates(start_date, end_date)
        output = io.StringIO(newline='')
        writer = csv.writer(output)

        def write_row(values):
            writer.writerow([ReportService._csv_cell(value) for value in values])

        conn = ReportService.get_connection()
        try:
            with conn.cursor() as cursor:
                start, end_exclusive = ReportService._resolve_dates(cursor, start, end)
                if report_type == 'daily_revenue':
                    write_row(['Đầu kỳ', 'Số đơn đã giao', 'Doanh thu đã giao (VNĐ)'])
                    rows = ReportService._group_revenue(
                        ReportService._daily_revenue(cursor, start, end_exclusive), group_by
                    )
                    for row in rows:
                        write_row([row.OrderDate.strftime('%d/%m/%Y'), row.OrderCount, row.DailyRevenue])
                elif report_type == 'best_selling':
                    write_row(['Tên sản phẩm (top 20)', 'Số lượng đã giao', 'Doanh thu sản phẩm đã giao (VNĐ)'])
                    for row in ReportService._best_selling(cursor, start, end_exclusive):
                        write_row([row.ProductName, row.TotalSold, row.TotalRevenue or 0])
                elif report_type == 'category_revenue':
                    write_row(['Danh mục', 'Số đơn đã giao', 'Doanh thu sản phẩm đã giao (VNĐ)'])
                    for row in ReportService._category_revenue(cursor, start, end_exclusive):
                        write_row([row.CategoryName, row.OrderCount, row.CategoryRevenue or 0])
                elif report_type == 'top_customers':
                    cursor.execute(
                        """
                        SELECT c.FullName, c.Email, COUNT(o.OrderID) AS OrderCount,
                               COALESCE(SUM(o.TotalAmount), 0) AS TotalSpent
                        FROM Customers c JOIN Orders o ON o.CustomerID = c.CustomerID
                        WHERE o.Status = 'Delivered' AND o.OrderDate >= %s AND o.OrderDate < %s
                        GROUP BY c.CustomerID, c.FullName, c.Email
                        ORDER BY TotalSpent DESC, c.CustomerID LIMIT 20
                    """,
                        (start, end_exclusive),
                    )
                    write_row(['Tên khách hàng (top 20)', 'Email', 'Số đơn đã giao', 'Chi tiêu đơn đã giao (VNĐ)'])
                    for row in cursor.fetchall():
                        write_row([row.FullName, row.Email, row.OrderCount, row.TotalSpent or 0])
                elif report_type == 'low_stock':
                    # Stock is a current inventory snapshot, not a sales/date report.
                    cursor.execute("""
                        SELECT p.ProductName, c.ColorName, s.SizeName, pv.Quantity
                        FROM ProductVariants pv JOIN Products p ON p.ProductID = pv.ProductID
                        JOIN Colors c ON c.ColorID = pv.ColorID JOIN Sizes s ON s.SizeID = pv.SizeID
                        WHERE pv.Quantity < 20 ORDER BY pv.Quantity, pv.VariantID LIMIT 50
                    """)
                    write_row(['Tồn kho hiện tại (top 50, không lọc ngày)', 'Màu', 'Size', 'Số lượng còn'])
                    for row in cursor.fetchall():
                        write_row([row.ProductName, row.ColorName, row.SizeName, row.Quantity])
                else:
                    cursor.execute(
                        """
                        SELECT o.OrderID, c.FullName, o.OrderDate, o.TotalAmount, o.Status, o.PaymentMethod
                        FROM Orders o JOIN Customers c ON c.CustomerID = o.CustomerID
                        WHERE o.Status = 'Delivered' AND o.OrderDate >= %s AND o.OrderDate < %s
                        ORDER BY o.OrderDate DESC, o.OrderID DESC LIMIT 100
                    """,
                        (start, end_exclusive),
                    )
                    write_row(
                        [
                            'Mã đơn (100 gần nhất)',
                            'Khách hàng',
                            'Ngày đặt',
                            'Giá trị đơn đã giao (VNĐ)',
                            'Trạng thái',
                            'Thanh toán',
                        ]
                    )
                    for row in cursor.fetchall():
                        write_row(
                            [
                                row.OrderID,
                                row.FullName,
                                row.OrderDate.strftime('%d/%m/%Y %H:%M'),
                                row.TotalAmount or 0,
                                row.Status,
                                row.PaymentMethod or 'N/A',
                            ]
                        )
        finally:
            conn.close()
        # Exactly one UTF-8 BOM, including for an empty report.
        return output.getvalue().encode('utf-8-sig')
