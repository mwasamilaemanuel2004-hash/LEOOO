"""Admin routes"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import db
from models.user import User
from models.settings import TradingSettings, ApiSettings
from models.trade import Trade
from models.portfolio import Portfolio
import logging

admin_bp = Blueprint('admin', __name__)
logger = logging.getLogger(__name__)

@admin_bp.route('/dashboard', methods=['GET'])
@jwt_required()
def admin_dashboard():
    """Admin dashboard statistics"""
    try:
        total_users = User.query.count()
        active_users = User.query.filter_by(is_active=True).count()
        total_trades = Trade.query.count()
        total_pnl = db.session.query(db.func.sum(Trade.pnl)).scalar() or 0
        
        return jsonify({
            'total_users': total_users,
            'active_users': active_users,
            'total_trades': total_trades,
            'total_pnl': total_pnl,
            'platform_status': 'OPERATIONAL'
        }), 200
    
    except Exception as e:
        logger.error(f'Admin dashboard error: {str(e)}')
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/users', methods=['GET'])
@jwt_required()
def list_users():
    """List all users"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        users = User.query.paginate(page=page, per_page=per_page)
        
        return jsonify({
            'users': [user.to_dict() for user in users.items],
            'total': users.total,
            'pages': users.pages,
            'current_page': page
        }), 200
    
    except Exception as e:
        logger.error(f'List users error: {str(e)}')
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/users/<user_id>', methods=['GET'])
@jwt_required()
def get_user_details(user_id):
    """Get user details"""
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        portfolio = Portfolio.query.filter_by(user_id=user_id).first()
        api_settings = ApiSettings.query.filter_by(user_id=user_id).first()
        trading_settings = TradingSettings.query.filter_by(user_id=user_id).first()
        
        return jsonify({
            'user': user.to_dict(),
            'portfolio': portfolio.to_dict() if portfolio else None,
            'api_configured': bool(api_settings),
            'trading_configured': bool(trading_settings)
        }), 200
    
    except Exception as e:
        logger.error(f'Get user details error: {str(e)}')
        return jsonify({'error': 'Internal server error'}), 500
