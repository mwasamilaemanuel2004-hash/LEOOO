"""Portfolio models"""

from app import db
from datetime import datetime
from sqlalchemy.dialects.postgresql import UUID
import uuid

class Portfolio(db.Model):
    """Portfolio model"""
    __tablename__ = 'portfolios'
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey('users.id'), nullable=False, unique=True)
    
    total_capital = db.Column(db.Float, default=0)  # Initial capital
    available_balance = db.Column(db.Float, default=0)  # Available for trading
    locked_balance = db.Column(db.Float, default=0)  # In open positions
    
    total_pnl = db.Column(db.Float, default=0)  # Cumulative P&L
    total_pnl_percent = db.Column(db.Float, default=0)
    
    total_trades = db.Column(db.Integer, default=0)
    winning_trades = db.Column(db.Integer, default=0)
    losing_trades = db.Column(db.Integer, default=0)
    win_rate = db.Column(db.Float, default=0)  # %
    
    max_drawdown = db.Column(db.Float, default=0)  # %
    current_drawdown = db.Column(db.Float, default=0)  # %
    
    sharpe_ratio = db.Column(db.Float, default=0)
    sortino_ratio = db.Column(db.Float, default=0)
    profit_factor = db.Column(db.Float, default=0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    metrics = db.relationship('PortfolioMetrics', backref='portfolio', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': str(self.id),
            'user_id': str(self.user_id),
            'total_capital': self.total_capital,
            'available_balance': self.available_balance,
            'locked_balance': self.locked_balance,
            'total_pnl': self.total_pnl,
            'total_pnl_percent': self.total_pnl_percent,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': self.win_rate,
            'max_drawdown': self.max_drawdown,
            'current_drawdown': self.current_drawdown,
            'sharpe_ratio': self.sharpe_ratio,
            'sortino_ratio': self.sortino_ratio,
            'profit_factor': self.profit_factor,
        }


class PortfolioMetrics(db.Model):
    """Portfolio metrics history"""
    __tablename__ = 'portfolio_metrics'
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    portfolio_id = db.Column(UUID(as_uuid=True), db.ForeignKey('portfolios.id'), nullable=False)
    
    timestamp = db.Column(db.DateTime, nullable=False, index=True)
    balance = db.Column(db.Float)
    pnl = db.Column(db.Float)
    pnl_percent = db.Column(db.Float)
    drawdown_percent = db.Column(db.Float)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
