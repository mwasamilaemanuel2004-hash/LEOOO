"""Trading routes"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import db
from models.trade import Trade, Position
from models.portfolio import Portfolio
import logging

trading_bp = Blueprint('trading', __name__)
logger = logging.getLogger(__name__)

@trading_bp.route('/trades', methods=['GET'])
@jwt_required()
def get_trades():
    """Get user trades"""
    try:
        identity = get_jwt_identity()
        user_id = identity.get('user_id')
        
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        trades = Trade.query.filter_by(user_id=user_id).paginate(page=page, per_page=per_page)
        
        return jsonify({
            'trades': [trade.to_dict() for trade in trades.items],
            'total': trades.total,
            'pages': trades.pages
        }), 200
    
    except Exception as e:
        logger.error(f'Get trades error: {str(e)}')
        return jsonify({'error': 'Internal server error'}), 500


@trading_bp.route('/positions', methods=['GET'])
@jwt_required()
def get_positions():
    """Get open positions"""
    try:
        identity = get_jwt_identity()
        user_id = identity.get('user_id')
        
        positions = Position.query.filter_by(user_id=user_id).all()
        
        return jsonify({
            'positions': [pos.to_dict() for pos in positions]
        }), 200
    
    except Exception as e:
        logger.error(f'Get positions error: {str(e)}')
        return jsonify({'error': 'Internal server error'}), 500


@trading_bp.route('/summary', methods=['GET'])
@jwt_required()
def get_trading_summary():
    """Get trading summary"""
    try:
        identity = get_jwt_identity()
        user_id = identity.get('user_id')
        
        portfolio = Portfolio.query.filter_by(user_id=user_id).first()
        open_positions = Position.query.filter_by(user_id=user_id).count()
        total_trades = Trade.query.filter_by(user_id=user_id).count()
        
        return jsonify({
            'portfolio': portfolio.to_dict() if portfolio else None,
            'open_positions': open_positions,
            'total_trades': total_trades
        }), 200
    
    except Exception as e:
        logger.error(f'Get trading summary error: {str(e)}')
        return jsonify({'error': 'Internal server error'}), 500
