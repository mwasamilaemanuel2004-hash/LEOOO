"""Health check routes"""

from flask import Blueprint, jsonify
from datetime import datetime

health_bp = Blueprint('health', __name__)

@health_bp.route('/status', methods=['GET'])
def health_status():
    """Health check endpoint"""
    return jsonify({
        'status': 'HEALTHY',
        'timestamp': datetime.utcnow().isoformat(),
        'service': 'REXM AI Trading Bot',
        'version': '1.0.0'
    }), 200
