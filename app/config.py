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
    EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
    EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
    EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', 'your_email@gmail.com')
    EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', 'your_app_password')
    EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True') == 'True'

    # Third Party
    PIXABAY_API_KEY = os.environ.get('PIXABAY_API_KEY', '50476586-5521aa05792328277ee09bd80')
    PIXABAY_ENDPOINT = 'https://pixabay.com/api/'
