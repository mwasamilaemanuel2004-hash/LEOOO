"""Portfolio routes"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import db
from models.portfolio import Portfolio, PortfolioMetrics
from models.trade import Trade
import logging

portfolio_bp = Blueprint('portfolio', __name__)
logger = logging.getLogger(__name__)

@portfolio_bp.route('/overview', methods=['GET'])
@jwt_required()
def get_portfolio_overview():
    """Get portfolio overview"""
    try:
        identity = get_jwt_identity()
        user_id = identity.get('user_id')
        
        portfolio = Portfolio.query.filter_by(user_id=user_id).first()
        
        if not portfolio:
            return jsonify({'error': 'Portfolio not found'}), 404
        
        return jsonify(portfolio.to_dict()), 200
    
    except Exception as e:
        logger.error(f'Portfolio overview error: {str(e)}')
        return jsonify({'error': 'Internal server error'}), 500


@portfolio_bp.route('/performance', methods=['GET'])
@jwt_required()
def get_portfolio_performance():
    """Get portfolio performance metrics"""
    try:
        identity = get_jwt_identity()
        user_id = identity.get('user_id')
        
        portfolio = Portfolio.query.filter_by(user_id=user_id).first()
        
        if not portfolio:
            return jsonify({'error': 'Portfolio not found'}), 404
        
        metrics = PortfolioMetrics.query.filter_by(portfolio_id=portfolio.id).all()
        
        return jsonify({
            'portfolio_id': str(portfolio.id),
            'metrics': [{
                'timestamp': m.timestamp.isoformat(),
                'balance': m.balance,
                'pnl': m.pnl,
                'pnl_percent': m.pnl_percent,
                'drawdown_percent': m.drawdown_percent
            } for m in metrics]
        }), 200
    
    except Exception as e:
        logger.error(f'Portfolio performance error: {str(e)}')
        return jsonify({'error': 'Internal server error'}), 500
