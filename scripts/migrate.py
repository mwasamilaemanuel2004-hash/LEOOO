"""Database migration script"""

from flask import Flask
from app import create_app, db
from models import (
    User, Admin, ApiSettings, TradingSettings,
    Trade, Position, Portfolio, PortfolioMetrics, Notification
)

if __name__ == '__main__':
    app = create_app()
    
    with app.app_context():
        print('Creating all database tables...')
        db.create_all()
        print('✅ Database migration completed successfully!')
        print('\nTables created:')
        print('  - users')
        print('  - admins')
        print('  - api_settings')
        print('  - trading_settings')
        print('  - trades')
        print('  - positions')
        print('  - portfolios')
        print('  - portfolio_metrics')
        print('  - notifications')
