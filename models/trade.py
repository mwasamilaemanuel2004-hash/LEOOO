"""Trade and Position models"""

from app import db
from datetime import datetime
from sqlalchemy.dialects.postgresql import UUID, JSON
import uuid

class Trade(db.Model):
    """Trade model - records all trades executed"""
    __tablename__ = 'trades'
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False)
    
    # Trade Details
    symbol = db.Column(db.String(20), nullable=False)  # BTC/USDT, ETH/USDT, etc.
    side = db.Column(db.String(10), nullable=False)  # BUY or SELL
    entry_price = db.Column(db.Float, nullable=False)
    entry_quantity = db.Column(db.Float, nullable=False)
    entry_time = db.Column(db.DateTime, nullable=False)
    
    # Exit Details
    exit_price = db.Column(db.Float)
    exit_quantity = db.Column(db.Float)
    exit_time = db.Column(db.DateTime)
    
    # Risk Management
    stop_loss = db.Column(db.Float)
    take_profit = db.Column(db.Float)
    risk_amount = db.Column(db.Float)
    
    # Performance
    pnl = db.Column(db.Float)  # Profit/Loss in USDT
    pnl_percent = db.Column(db.Float)  # Profit/Loss in %
    status = db.Column(db.String(20), default='OPEN')  # OPEN, CLOSED, CANCELLED
    
    # Strategy & AI
    strategy_used = db.Column(db.String(100))
    timeframe = db.Column(db.Integer)  # 5, 15, 60, 240, 1440 (minutes)
    ai_confidence = db.Column(db.Float)  # 0-1
    
    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': str(self.id),
            'user_id': str(self.user_id),
            'symbol': self.symbol,
            'side': self.side,
            'entry_price': self.entry_price,
            'entry_quantity': self.entry_quantity,
            'entry_time': self.entry_time.isoformat(),
            'exit_price': self.exit_price,
            'exit_time': self.exit_time.isoformat() if self.exit_time else None,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'pnl': self.pnl,
            'pnl_percent': self.pnl_percent,
            'status': self.status,
            'strategy_used': self.strategy_used,
            'timeframe': self.timeframe,
            'ai_confidence': self.ai_confidence,
            'created_at': self.created_at.isoformat(),
        }


class Position(db.Model):
    """Active Position model"""
    __tablename__ = 'positions'
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False)
    trade_id = db.Column(UUID(as_uuid=True), db.ForeignKey('trades.id'))
    
    symbol = db.Column(db.String(20), nullable=False)
    side = db.Column(db.String(10), nullable=False)  # LONG or SHORT
    quantity = db.Column(db.Float, nullable=False)
    entry_price = db.Column(db.Float, nullable=False)
    current_price = db.Column(db.Float)
    unrealized_pnl = db.Column(db.Float)
    unrealized_pnl_percent = db.Column(db.Float)
    
    stop_loss = db.Column(db.Float)
    take_profit = db.Column(db.Float)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': str(self.id),
            'symbol': self.symbol,
            'side': self.side,
            'quantity': self.quantity,
            'entry_price': self.entry_price,
            'current_price': self.current_price,
            'unrealized_pnl': self.unrealized_pnl,
            'unrealized_pnl_percent': self.unrealized_pnl_percent,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
        }
