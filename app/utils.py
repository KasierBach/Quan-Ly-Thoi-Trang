import json
import decimal
import unicodedata
import re
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app

# Hàm chuyển đổi decimal sang float cho JSON
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            return float(o)
        return super(DecimalEncoder, self).default(self, o)

# Helper function for slugify
def slugify(text):
    if not text:
        return ''
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    text = re.sub(r'[^\w\s-]', '', text).strip().lower()
    return re.sub(r'[-\s]+', '-', text)

# Hàm gửi email
def send_email(to_email, subject, html_content):
    try:
        msg = MIMEMultipart()
        # Use current_app.config to access email settings
        email_user = current_app.config['EMAIL_HOST_USER']
        email_password = current_app.config['EMAIL_HOST_PASSWORD']
        email_host = current_app.config['EMAIL_HOST']
        email_port = current_app.config['EMAIL_PORT']
        
        msg['From'] = email_user
        msg['To'] = to_email
        msg['Subject'] = subject
        
        msg.attach(MIMEText(html_content, 'html'))
        
        server = smtplib.SMTP(email_host, email_port)
        server.starttls()
        server.login(email_user, email_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Error sending email: {str(e)}")
        return False

# Template filter to resolve image path
def resolve_image(obj):
    # Default image
    default_image = 'images/default.jpg'
    
    if not obj:
        return default_image
        
    # Check if object is a dict
    is_dict = isinstance(obj, dict)
    
    # 1. Check direct ImageURL
    image_url = obj.get('ImageURL') if is_dict else getattr(obj, 'ImageURL', None)
    if image_url:
        return image_url
        
    # 2. Check by ID
    obj_id = obj.get('ProductID') if is_dict else getattr(obj, 'ProductID', None)
    if not obj_id:
         # Try category ID
         obj_id = obj.get('CategoryID') if is_dict else getattr(obj, 'CategoryID', None)
         
    if obj_id:
        # Check standard extensions
        for ext in ['.jpg', '.png', '.jpeg']:
            filename = f"images/{obj_id}{ext}"
            filepath = os.path.join(current_app.root_path, 'static', filename)
            if os.path.exists(filepath):
                return filename

    # 3. Check by Name (Slug)
    name = obj.get('ProductName') if is_dict else getattr(obj, 'ProductName', None)
    if not name:
        name = obj.get('CategoryName') if is_dict else getattr(obj, 'CategoryName', None)
        
    if name:
        slug = slugify(name)
        for ext in ['.jpg', '.png', '.jpeg']:
            filename = f"images/{slug}{ext}"
            filepath = os.path.join(current_app.root_path, 'static', filename)
            if os.path.exists(filepath):
                return filename
            
        # Try common variations if needed (optional)
        
    return default_image
