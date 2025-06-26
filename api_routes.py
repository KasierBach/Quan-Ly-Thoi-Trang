from flask import Blueprint, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
import pyodbc
import decimal
import json
from datetime import datetime

# Import the get_db_connection function from your main app
from app import get_db_connection

api = Blueprint('api', __name__)

# API endpoint to get product reviews
@api.route('/api/get_product_reviews', methods=['GET'])
def get_product_reviews():
    product_id = request.args.get('product_id', type=int)
    
    if not product_id:
        return jsonify({'success': False, 'message': 'Product ID is required'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get product reviews
        cursor.execute('''
            SELECT r.ReviewID, r.Rating, r.Comment, r.ReviewDate, c.FullName AS CustomerName
            FROM Reviews r
            JOIN Customers c ON r.CustomerID = c.CustomerID
            WHERE r.ProductID = ?
            ORDER BY r.ReviewDate DESC
        ''', product_id)
        
        reviews_data = cursor.fetchall()
        
        # Calculate average rating
        cursor.execute('''
            SELECT AVG(CAST(Rating AS FLOAT)) AS AverageRating
            FROM Reviews
            WHERE ProductID = ?
        ''', product_id)
        
        avg_rating = cursor.fetchone()
        average_rating = avg_rating.AverageRating if avg_rating and avg_rating.AverageRating else 0
        
        # Format reviews
        reviews = []
        for review in reviews_data:
            reviews.append({
                'review_id': review.ReviewID,
                'rating': review.Rating,
                'comment': review.Comment,
                'review_date': review.ReviewDate.strftime('%d/%m/%Y'),
                'customer_name': review.CustomerName
            })
        
        return jsonify({
            'success': True,
            'reviews': reviews,
            'average_rating': float(average_rating),
            'review_count': len(reviews)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

# Add this to your main app.py to register the blueprint
# from api_routes import api
# app.register_blueprint(api)
