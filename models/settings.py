"""Settings models"""

from app import db
from datetime import datetime
from sqlalchemy.dialects.postgresql import UUID, JSON
import uuid

class ApiSettings(db.Model):
    """API Settings model - stores Binance API keys and configurations"""
    __tablename__ = 'api_settings'
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False)
    
    # Binance API
    binance_api_key = db.Column(db.String(255), nullable=False)
    binance_secret_key = db.Column(db.String(255), nullable=False)
    binance_testnet = db.Column(db.Boolean, default=True)
    
    # IP Configuration
    assigned_ipv4 = db.Column(db.String(15))
    ip_whitelist = db.Column(JSON, default=[])
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    last_validated = db.Column(db.DateTime)
    validation_status = db.Column(db.String(50))  # valid, invalid, pending
    
    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self, include_secrets=False):
        """Convert to dictionary"""
        data = {
            'id': str(self.id),
            'user_id': str(self.user_id),
            'binance_testnet': self.binance_testnet,
            'assigned_ipv4': self.assigned_ipv4,
            'ip_whitelist': self.ip_whitelist,
            'is_active': self.is_active,
            'validation_status': self.validation_status,
            'created_at': self.created_at.isoformat(),
        }
        
        if include_secrets:
            data['binance_api_key'] = self.binance_api_key
            data['binance_secret_key'] = self.binance_secret_key
        
        return data


class TradingSettings(db.Model):
    """Trading Settings model"""
    __tablename__ = 'trading_settings'
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False, unique=True)
    
    # Capital Configuration
    capital_size_usdt = db.Column(db.Float, nullable=False)  # 5 to 1000 USDT
    
    # Profit Target
    profit_target_percent = db.Column(db.Float, nullable=False)  # 0.8 to 50%
    
    # Risk Management
    max_loss_per_trade_percent = db.Column(db.Float, default=2.0)
    max_daily_loss_percent = db.Column(db.Float, default=5.0)
    max_weekly_loss_percent = db.Column(db.Float, default=10.0)
    max_monthly_loss_percent = db.Column(db.Float, default=15.0)
    max_drawdown_percent = db.Column(db.Float, default=20.0)
    
    # Trading Strategies
    enabled_strategies = db.Column(JSON, default=[
        'market_making',
        'mean_reversion',
        'momentum_trading',
        'cross_exchange_arbitrage'
    ])
    
    # Timeframes
    scalping_enabled = db.Column(db.Boolean, default=True)
    intraday_enabled = db.Column(db.Boolean, default=True)
    swing_enabled = db.Column(db.Boolean, default=True)
    
    # Bot Configuration
    bot_instances = db.Column(db.Integer, default=2)
    
    # Auto-trading
    auto_trading_enabled = db.Column(db.Boolean, default=False)
    
    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': str(self.id),
            'user_id': str(self.user_id),
            'capital_size_usdt': self.capital_size_usdt,
            'profit_target_percent': self.profit_target_percent,
            'max_loss_per_trade_percent': self.max_loss_per_trade_percent,
            'max_daily_loss_percent': self.max_daily_loss_percent,
            'max_weekly_loss_percent': self.max_weekly_loss_percent,
            'max_monthly_loss_percent': self.max_monthly_loss_percent,
            'max_drawdown_percent': self.max_drawdown_percent,
            'enabled_strategies': self.enabled_strategies,
            'scalping_enabled': self.scalping_enabled,
            'intraday_enabled': self.intraday_enabled,
            'swing_enabled': self.swing_enabled,
            'bot_instances': self.bot_instances,
            'auto_trading_enabled': self.auto_trading_enabled,
            'created_at': self.created_at.isoformat(),
        }
