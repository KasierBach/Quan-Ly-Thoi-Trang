import os
import requests
from flask import current_app
from .base_service import BaseService

class MediaService(BaseService):
    @staticmethod
    def search_pixabay(query):
        """Search for images on Pixabay."""
        if not query: return {'success': False, 'message': 'Query is required'}
        
        try:
            params = {
                'key': current_app.config['PIXABAY_API_KEY'], 
                'q': query,
                'image_type': 'photo',
                'per_page': 20,
                'safesearch': 'true'
            }
            resp = requests.get(current_app.config['PIXABAY_ENDPOINT'], params=params, timeout=10)
            resp.raise_for_status()
            return {'success': True, 'hits': resp.json().get('hits', [])}
        except Exception as e:
            return MediaService.handle_error(e)

    @staticmethod
    def save_pixabay_image(image_url, product_id):
        """Download image from Pixabay and save it locally for a product."""
        if not image_url or not product_id: 
            return {'success': False, 'message': 'Image URL and Product ID are required'}
        
        try:
            # Ensure folder exists
            image_folder = os.path.join(current_app.root_path, 'static', 'images')
            os.makedirs(image_folder, exist_ok=True)
            
            filename = f"{product_id}.jpg"
            filepath = os.path.join(image_folder, filename)
            
            # Download
            response = requests.get(image_url, timeout=15)
            response.raise_for_status()
            
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            return {'success': True, 'path': f"images/{filename}"}
        except Exception as e:
            return MediaService.handle_error(e)
