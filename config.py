"""
REXM AI Trading Bot - Configuration Module
Ultimate Elite Institutional AI Hedge Fund Trading Ecosystem
"""

import os
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()

class Config:
    """Base configuration"""
    
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'jwt-secret-key-change-in-production')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=24)
    
    # Database
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'postgresql://localhost/rexm_ai')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Redis
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    
    # Admin
    ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'eestradingmachine@gmail.com')
    ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'esMwas@2004')
    
    # Binance
    BINANCE_API_KEY = os.getenv('BINANCE_API_KEY')
    BINANCE_SECRET_KEY = os.getenv('BINANCE_SECRET_KEY')
    BINANCE_TESTNET = os.getenv('BINANCE_TESTNET', 'True').lower() == 'true'
    
    # Trading Parameters
    MIN_CAPITAL_USDT = float(os.getenv('MIN_CAPITAL', 5))
    MAX_CAPITAL_USDT = float(os.getenv('MAX_CAPITAL', 1000))
    MIN_PROFIT_TARGET = float(os.getenv('MIN_PROFIT_TARGET', 0.8))
    MAX_PROFIT_TARGET = float(os.getenv('MAX_PROFIT_TARGET', 50))
    
    # IP Configuration
    PUBLIC_IPV4 = os.getenv('PUBLIC_IPV4')
    BOT_INSTANCES = int(os.getenv('BOT_INSTANCES', 2))
    
    # Notifications
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
    
    # Timeframes (minutes)
    SCALPING_TIMEFRAMES = [5, 10, 15]
    INTRADAY_TIMEFRAMES = [30, 60, 240]
    SWING_TIMEFRAMES = [720, 1440]
    
    # Risk Management Thresholds
    MAX_DAILY_LOSS_PERCENT = float(os.getenv('MAX_DAILY_LOSS_PERCENT', 5))
    MAX_WEEKLY_LOSS_PERCENT = float(os.getenv('MAX_WEEKLY_LOSS_PERCENT', 10))
    MAX_MONTHLY_LOSS_PERCENT = float(os.getenv('MAX_MONTHLY_LOSS_PERCENT', 15))
    MAX_DRAWDOWN_PERCENT = float(os.getenv('MAX_DRAWDOWN_PERCENT', 20))
    
    # Trading Strategies
    ENABLED_STRATEGIES = [
        'market_making',
        'statistical_arbitrage',
        'pair_trading',
        'momentum_trading',
        'mean_reversion',
        'cross_exchange_arbitrage',
        'funding_rate_arbitrage',
        'volatility_arbitrage',
        'delta_neutral',
        'basis_trading',
        'basket_trading',
        'trend_following',
        'smart_money_tracking',
    ]
    
    # Performance Targets
    TARGET_SHARPE_RATIO = 2.0
    TARGET_SORTINO_RATIO = 2.5
    TARGET_UPTIME_PERCENT = 99.9
    
    # Security
    PASSWORD_MIN_LENGTH = 12
    REQUIRE_2FA = True
    IP_WHITELIST_ENABLED = True
    
    # Compliance
    KYC_REQUIRED = True
    AML_CHECKS_ENABLED = True


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    BINANCE_TESTNET = True


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    BINANCE_TESTNET = False


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    BINANCE_TESTNET = True


# Configuration dictionary
config_dict = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}

# Get active configuration
def get_config():
    """Get configuration based on environment"""
    env = os.getenv('FLASK_ENV', 'development')
    return config_dict.get(env, DevelopmentConfig)
