import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # App Secret
    SECRET_KEY = os.environ.get('SECRET_KEY', 'fashion_store_secret_key')

    # Database
    # Handle postgres:// vs postgresql:// fix for Vercel/Render
    database_url = os.environ.get('DATABASE_URL')
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    
    SQLALCHEMY_DATABASE_URI = database_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Email
    MAIL_SERVER = os.environ.get('MAIL_SERVER') or os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or os.environ.get('EMAIL_PORT', 465))
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME') or os.environ.get('EMAIL_HOST_USER')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD') or os.environ.get('EMAIL_HOST_PASSWORD')
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'False') == 'True'
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'True') == 'True'
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or MAIL_USERNAME

    # Third Party
    PIXABAY_API_KEY = os.environ.get('PIXABAY_API_KEY', '50476586-5521aa05792328277ee09bd80')
    PIXABAY_ENDPOINT = 'https://pixabay.com/api/'
