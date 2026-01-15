import psycopg2
from psycopg2.extras import NamedTupleCursor
import os
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

# Sample data templates
REVIEWS_TEMPLATES = [
    (5, "Chất lượng sản phẩm tuyệt vời, vải mặc rất mát và thoải mái. Rất đáng tiền!"),
    (5, "Giao hàng cực kỳ nhanh, đóng gói cẩn thận. Sản phẩm đúng như mô tả."),
    (5, "Đồ đẹp lắm shop ơi, mặc lên form chuẩn luôn. Sẽ ủng hộ shop dài dài."),
    (4, "Sản phẩm tốt, màu sắc hơi đậm hơn trong hình một chút nhưng vẫn rất đẹp."),
    (4, "Vải hơi mỏng một tẹo nhưng form dáng ổn, mặc đi chơi rất hợp."),
    (4, "Ok, hàng đẹp, đúng size. Thời gian giao hàng hơi lâu một chút."),
    (3, "Bình thường, chất liệu tạm ổn so với giá tiền."),
    (3, "Màu sắc không giống ảnh lắm, nhưng mặc vẫn được. Tạm chấp nhận."),
    (3, "Size hơi rộng so với bảng size của shop, lần sau mình sẽ lấy s' nhỏ hơn."),
    (2, "Hơi thất vọng vì chất vải không như mong đợi, sờ vào thấy hơi thô."),
    (2, "Đường chỉ may chưa được tinh tế lắm, còn nhiều chỉ thừa."),
    (1, "Sản phẩm quá tệ, không giống mô tả tí nào. Mọi người nên cân nhắc."),
    (1, "Thất vọng quá, mua về không mặc được vì chất lượng kém.")
]

COMMENTS_TEMPLATES = [
    "Shop ơi cho mình hỏi size L còn màu đen không ạ?",
    "Mẫu này cao 1m7 nặng 65kg thì mặc size gì vừa shop?",
    "Vải này là chất liệu gì vậy shop? Có co giãn không?",
    "Ship về Hà Nội thì mất bao lâu shop nhỉ?",
    "Sản phẩm này có được kiểm tra hàng trước khi nhận không shop?",
    "Mình muốn mua sỉ thì liên hệ thế nào ạ?",
    "Có mẫu nào tương tự nhưng màu xanh lá không shop?",
    "Áo này có bị ra màu khi giặt không ạ?",
    "Đồ đẹp quá, chúc shop đắt hàng nhé!"
]

ADMIN_REPLIES = [
    "Chào bạn, mẫu này size L bên mình còn đen nhé. Bạn nhắn tin cho shop để đặt hàng ạ!",
    "Dạ 1m7 65kg thì mặc size L là chuẩn form nhất bạn nhé. Bạn tham khảo bảng size chi tiết ở mô tả ạ.",
    "Bên mình cam kết chất vải 100% cotton cao cấp, mặc siêu mát luôn ạ.",
    "Dạ ship Hà Nội thường mất 2-3 ngày làm việc bạn nha.",
    "Chào bạn, quy định của shop là được đồng kiểm khi nhận hàng nên bạn cứ yên tâm nhé!",
    "Cảm ơn bạn đã quan tâm, shop đã inbox thông tin liên hệ sỉ cho bạn rồi ạ.",
    "Dạ hiện mẫu này chỉ có các màu như trên web thôi ạ, bạn tham khảo thêm các mẫu khác của shop nhé!",
    "Chào bạn, sản phẩm bên mình được xử lý chống phai màu nên bạn yên tâm giặt thoải mái nha.",
    "Cảm ơn bạn rất nhiều! Hy vọng bạn sẽ hài lòng với sản phẩm của shop."
]

def create_sample_data():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Get all ProductIDs
        cur.execute("SELECT ProductID FROM Products")
        product_ids = [row[0] for row in cur.fetchall()]

        # Get all CustomerIDs (excluding admin if we want, but let's include all 1-10)
        cur.execute("SELECT CustomerID FROM Customers WHERE IsAdmin = FALSE")
        customer_ids = [row[0] for row in cur.fetchall()]

        if not product_ids or not customer_ids:
            print("Lỗi: Không tìm thấy sản phẩm hoặc khách hàng trong database.")
            return

        print(f"Bắt đầu tạo dữ liệu cho {len(product_ids)} sản phẩm...")

        # Clear existing reviews and comments to make it "new"
        cur.execute("TRUNCATE TABLE Reviews, ProductComments RESTART IDENTITY CASCADE")
        
        for pid in product_ids:
            # Generate 2-5 reviews per product
            num_reviews = random.randint(2, 5)
            reviewers = random.sample(customer_ids, min(num_reviews, len(customer_ids)))
            
            for cid in reviewers:
                rating, comment = random.choice(REVIEWS_TEMPLATES)
                review_date = datetime.now() - timedelta(days=random.randint(0, 30), hours=random.randint(0, 24))
                cur.execute(
                    "INSERT INTO Reviews (CustomerID, ProductID, Rating, Comment, ReviewDate) VALUES (%s, %s, %s, %s, %s)",
                    (cid, pid, rating, comment, review_date)
                )

            # Generate 1-4 comments per product
            num_comments = random.randint(1, 4)
            commenters = random.sample(customer_ids, min(num_comments, len(customer_ids)))

            for cid in commenters:
                content = random.choice(COMMENTS_TEMPLATES)
                comment_date = datetime.now() - timedelta(days=random.randint(0, 30), hours=random.randint(0, 24))
                
                # Randomly decide if there's an admin reply (50% chance)
                admin_reply = None
                reply_date = None
                if random.random() > 0.5:
                    admin_reply = random.choice(ADMIN_REPLIES)
                    reply_date = comment_date + timedelta(hours=random.randint(1, 48))

                cur.execute(
                    "INSERT INTO ProductComments (CustomerID, ProductID, Content, CommentDate, AdminReply, ReplyDate, IsVisible) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (cid, pid, content, comment_date, admin_reply, reply_date, True)
                )

        conn.commit()
        print("Tạo dữ liệu mẫu hoàn tất thành công!")

    except Exception as e:
        print(f"Đã xảy ra lỗi: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    create_sample_data()
