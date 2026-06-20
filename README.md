# REXM AI Trading Bot
## Ultimate Elite Institutional AI Hedge Fund Trading Ecosystem

### Core Features

✅ **Multi-Agent AI Architecture**
- Chief Investment Officer (CIO) AI
- Chief Risk Officer (CRO) AI
- Compliance & Regulatory AI
- Market Regime AI
- Quant Research AI

✅ **Trading Capabilities**
- Multi-timeframe trading (5m, 15m, 1h, 4h, Daily)
- Advanced strategies (Arbitrage, Mean Reversion, Momentum)
- Scalping, Intraday, and Swing Trading
- Triangular arbitrage
- Cross-exchange arbitrage

✅ **Risk Management**
- Dynamic capital protection
- Daily/Weekly/Monthly loss limits
- Maximum drawdown controls
- Stop-loss and take-profit automation
- Position sizing algorithms

✅ **Admin Dashboard**
- Email: `eestradingmachine@gmail.com`
- Admin login with role-based access
- Real-time trading monitoring
- Portfolio analytics
- System health monitoring

✅ **API Integration**
- Binance API support
- API key management
- IP whitelisting
- Secure credential storage

✅ **User Settings**
- Capital configuration (5-1000 USDT)
- Profit target settings (0.8-50%)
- Risk parameters customization
- Trading strategy selection
- Bot instance management

### Installation

1. **Clone repository**
```bash
git clone https://github.com/yourusername/rexm-ai.git
cd rexm-ai
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Set up environment**
```bash
cp .env.example .env
# Edit .env with your settings
```

4. **Run locally**
```bash
flask run
```

### Deployment

**Deploy to Fly.io**
```bash
fly deploy
```

### API Endpoints

**Authentication**
- `POST /api/auth/admin/login` - Admin login
- `POST /api/auth/register` - User registration
- `POST /api/auth/login` - User login

**Settings**
- `POST /api/settings/api-settings` - Configure Binance API
- `GET /api/settings/api-settings` - Get API settings
- `POST /api/settings/trading-settings` - Configure trading
- `GET /api/settings/trading-settings` - Get trading settings

**Trading**
- `GET /api/trading/trades` - Get all trades
- `GET /api/trading/positions` - Get open positions
- `GET /api/trading/summary` - Get trading summary

**Portfolio**
- `GET /api/portfolio/overview` - Portfolio overview
- `GET /api/portfolio/performance` - Performance metrics

**Admin**
- `GET /api/admin/dashboard` - Admin dashboard
- `GET /api/admin/users` - List users
- `GET /api/admin/users/<user_id>` - User details

### Security Features

✅ JWT authentication
✅ Password hashing with bcrypt
✅ 2FA support
✅ IP whitelisting
✅ API key encryption
✅ Audit logging

### Performance Targets

- Sharpe Ratio > 2.0
- Sortino Ratio > 2.5
- 99.9% uptime
- Sub-millisecond trade execution

### Support

Admin Email: `eestradingmachine@gmail.com`

### License

MIT License
