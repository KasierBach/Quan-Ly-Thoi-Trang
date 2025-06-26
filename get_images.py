import os
import requests
import pyodbc
import time

# --- Cấu hình Pixabay ---
PIXABAY_API_KEY = '50476586-5521aa05792328277ee09bd80'
PIXABAY_ENDPOINT = 'https://pixabay.com/api/'

# Thư mục lưu ảnh
PROJECT_ROOT = os.path.dirname(__file__)
IMAGE_FOLDER = os.path.join(PROJECT_ROOT, 'static', 'images')
if not os.path.exists(IMAGE_FOLDER):
    os.makedirs(IMAGE_FOLDER, exist_ok=True)

# Kết nối SQL Server: thay DRIVER, SERVER, DATABASE, UID, PWD
CONN_STR = (
    'DRIVER={ODBC Driver 17 for SQL Server};'
    r'SERVER=DESKTOP-0NO7KHL\MSSQLSERVER69;'
    'DATABASE=FashionStoreDB;'
    'UID=sa;'
    'PWD=lolnani2;'
)

# Mapping tên sản phẩm tiếng Việt -> query tiếng Anh cho Pixabay
SEARCH_TERMS = {
    'Áo sơ mi nam trắng': 'white men dress shirt',
    'Áo thun nam đen': 'black men t-shirt',
    'Áo sơ mi nam kẻ sọc': 'striped men dress shirt',
    'Áo polo nam thể thao': 'men sporty polo shirt',
    'Áo khoác nam jean': 'men denim jacket',
    'Áo khoác gió nam': 'men windbreaker',
    'Áo ba lỗ nam': 'men sleeveless tank top',
    'Áo len nam cổ tròn': 'men crewneck sweater',
    'Áo sơ mi nữ trắng': 'white women blouse',
    'Áo thun nữ hồng': 'pink women t-shirt',
    'Áo kiểu nữ công sở': 'women office blouse',
    'Áo khoác nữ nhẹ': 'women lightweight jacket',
    'Áo ba lỗ nữ': 'women sleeveless tank top',
    'Áo len nữ cổ tim': 'women v-neck sweater',
    'Quần jean nam xanh': 'blue jeans men',
    'Quần kaki nam nâu': 'brown khaki pants men',
    'Quần short nam kaki': 'men khaki shorts',
    'Quần jogger nam': 'men jogger pants',
    'Quần jean nữ xanh nhạt': 'light blue jeans women',
    'Quần culottes nữ': 'women culottes',
    'Quần legging nữ thể thao': 'women athletic leggings',
    'Váy đầm suông đen': 'black shift dress women',
    'Váy đầm xòe hoa': 'women floral flare dress',
    'Váy liền thân công sở': 'women work dress',
    'Đầm maxi đi biển': 'women beach maxi dress',
    'Thắt lưng da nam': 'men leather belt',
    'Mũ bucket thời trang': 'fashion bucket hat',
    'Túi xách nữ công sở': 'women office handbag',
    'Áo khoác da nam': 'men leather jacket',
    'Áo len nữ cổ lọ': 'women turtleneck sweater',
    'Áo hoodie nam': 'men hooded sweatshirt',
    'Áo hoodie nữ': 'women hooded sweatshirt',
    'Quần shorts nữ': 'women shorts',
    'Chân váy chữ A': 'women a-line skirt',
    'Váy maxi dài': 'women maxi dress',
    'Giày thể thao nam': 'men sneakers',
    'Giày cao gót nữ': 'women high heels',
    'Túi xách da nam': 'men leather handbag',
    'Túi xách da nữ': 'women leather handbag',
    'Mũ len nữ': 'women knit beanie'
}

# Hàm fetch URL ảnh từ Pixabay, trả về list các URL

def fetch_pixabay_images(query, per_page=5):
    params = {
        'key': PIXABAY_API_KEY, 
        'q': query,
        'image_type': 'photo',
        'per_page': per_page,
        'safesearch': 'true'
    }
    resp = requests.get(PIXABAY_ENDPOINT, params=params, timeout=10)
    resp.raise_for_status()
    hits = resp.json().get('hits', [])
    return [hit.get('webformatURL') for hit in hits]

# Hàm tải file từ URL với retry
def download_image(url, filepath, retries=3, delay=1):
    for attempt in range(1, retries+1):
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            with open(filepath, 'wb') as f:
                f.write(r.content)
            return True
        except Exception as e:
            print(f"Attempt {attempt}/{retries} failed: {e}")
            time.sleep(delay)
    return False

# --- Thực thi chính ---
def main():
    conn = pyodbc.connect(CONN_STR)
    cursor = conn.cursor()
    cursor.execute("SELECT ProductID, ProductName FROM Products WHERE ImageURL IS NULL OR ImageURL = ''")
    products = cursor.fetchall()

    for pid, name in products:
        query = SEARCH_TERMS.get(name, name)
        print(f"\nProcessing [{pid}]: '{name}' -> searching '{query}'")
        candidates = fetch_pixabay_images(query)
        if not candidates:
            print(f"[ERROR] No candidates for '{query}'")
            continue

        for idx, url in enumerate(candidates, start=1):
            print(f"  {idx}. {url}")
        choice = input(f"Choose image [1-{len(candidates)}] for {name} (0 to skip): ")
        try:
            idx = int(choice)
            if idx <= 0 or idx > len(candidates):
                print("Skipped.")
                continue
            img_url = candidates[idx-1]
        except ValueError:
            print("Invalid input, skip.")
            continue

        filename = f"{pid}.jpg"
        filepath = os.path.join(IMAGE_FOLDER, filename)
        if download_image(img_url, filepath):
            relative = f"/static/images/{filename}"
            cursor.execute("UPDATE Products SET ImageURL = ? WHERE ProductID = ?", relative, pid)
            conn.commit()
            print(f"[OK] Saved {relative}")
        else:
            print(f"[ERROR] Download failed: {img_url}")

    cursor.close()
    conn.close()
    print("Finished processing images.")

if __name__ == '__main__':
    main()