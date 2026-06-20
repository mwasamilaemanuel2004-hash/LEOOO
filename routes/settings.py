"""Settings routes"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app import db
from models.settings import ApiSettings, TradingSettings
from models.user import User
import logging

settings_bp = Blueprint('settings', __name__)
logger = logging.getLogger(__name__)

@settings_bp.route('/api-settings', methods=['POST'])
@jwt_required()
def create_api_settings():
    """Create or update API settings"""
    try:
        identity = get_jwt_identity()
        user_id = identity.get('user_id')
        
        data = request.get_json()
        
        # Check existing settings
        settings = ApiSettings.query.filter_by(user_id=user_id).first()
        
        if settings:
            settings.binance_api_key = data.get('binance_api_key', settings.binance_api_key)
            settings.binance_secret_key = data.get('binance_secret_key', settings.binance_secret_key)
            settings.binance_testnet = data.get('binance_testnet', settings.binance_testnet)
            settings.assigned_ipv4 = data.get('assigned_ipv4')
            settings.ip_whitelist = data.get('ip_whitelist', [])
        else:
            settings = ApiSettings(
                user_id=user_id,
                binance_api_key=data.get('binance_api_key'),
                binance_secret_key=data.get('binance_secret_key'),
                binance_testnet=data.get('binance_testnet', True),
                assigned_ipv4=data.get('assigned_ipv4'),
                ip_whitelist=data.get('ip_whitelist', [])
            )
        
        db.session.add(settings)
        db.session.commit()
        
        return jsonify({
            'message': 'API settings updated successfully',
            'settings': settings.to_dict()
        }), 200
    
    except Exception as e:
        db.session.rollback()
        logger.error(f'API settings error: {str(e)}')
        return jsonify({'error': 'Failed to update API settings'}), 500


@settings_bp.route('/api-settings', methods=['GET'])
@jwt_required()
def get_api_settings():
    """Get API settings"""
    try:
        identity = get_jwt_identity()
        user_id = identity.get('user_id')
        
        settings = ApiSettings.query.filter_by(user_id=user_id).first()
        
        if not settings:
            return jsonify({'error': 'API settings not found'}), 404
        
        return jsonify(settings.to_dict()), 200
    
    except Exception as e:
        logger.error(f'Get API settings error: {str(e)}')
        return jsonify({'error': 'Internal server error'}), 500


@settings_bp.route('/trading-settings', methods=['POST'])
@jwt_required()
def create_trading_settings():
    """Create or update trading settings"""
    try:
        identity = get_jwt_identity()
        user_id = identity.get('user_id')
        
        data = request.get_json()
        
        # Validate capital
        capital = data.get('capital_size_usdt')
        if capital < 5 or capital > 1000:
            return jsonify({'error': 'Capital must be between 5-1000 USDT'}), 400
        
        # Validate profit target
        profit_target = data.get('profit_target_percent')
        if profit_target < 0.8 or profit_target > 50:
            return jsonify({'error': 'Profit target must be between 0.8-50%'}), 400
        
        # Check existing settings
        settings = TradingSettings.query.filter_by(user_id=user_id).first()
        
        if settings:
            settings.capital_size_usdt = capital
            settings.profit_target_percent = profit_target
            settings.max_loss_per_trade_percent = data.get('max_loss_per_trade_percent', 2.0)
            settings.enabled_strategies = data.get('enabled_strategies', [])
            settings.bot_instances = data.get('bot_instances', 2)
        else:
            settings = TradingSettings(
                user_id=user_id,
                capital_size_usdt=capital,
                profit_target_percent=profit_target,
                max_loss_per_trade_percent=data.get('max_loss_per_trade_percent', 2.0),
                enabled_strategies=data.get('enabled_strategies', []),
                bot_instances=data.get('bot_instances', 2)
            )
        
        db.session.add(settings)
        db.session.commit()
        
        return jsonify({
            'message': 'Trading settings updated successfully',
            'settings': settings.to_dict()
        }), 200
    
    except Exception as e:
        db.session.rollback()
        logger.error(f'Trading settings error: {str(e)}')
        return jsonify({'error': 'Failed to update trading settings'}), 500


@settings_bp.route('/trading-settings', methods=['GET'])
@jwt_required()
def get_trading_settings():
    """Get trading settings"""
    try:
        identity = get_jwt_identity()
        user_id = identity.get('user_id')
        
        settings = TradingSettings.query.filter_by(user_id=user_id).first()
        
        if not settings:
            return jsonify({'error': 'Trading settings not found'}), 404
        
        return jsonify(settings.to_dict()), 200
    
    except Exception as e:
        logger.error(f'Get trading settings error: {str(e)}')
        return jsonify({'error': 'Internal server error'}), 500
