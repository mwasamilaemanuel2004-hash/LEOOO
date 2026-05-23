# ═══════════════════════════════════════════════════════
# estrading.machine v9 GODMODE — Complete Requirements
# ═══════════════════════════════════════════════════════

# Core Framework
fastapi==0.110.0
uvicorn[standard]==0.27.1
python-multipart==0.0.9
starlette==0.36.3

# Database
supabase==2.3.4
postgrest==0.16.1

# HTTP Client
httpx==0.26.0
aiohttp==3.9.3
websockets==12.0
requests==2.31.0

# AI/ML (pure numpy — no PyTorch needed)
numpy==1.26.4
pandas==2.2.0
scipy==1.12.0

# Auth & Security
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
PyJWT==2.8.0
cryptography==42.0.5
python-dotenv==1.0.1

# Validation
pydantic==2.6.1
pydantic-settings==2.2.1

# Logging
structlog==24.1.0
colorama==0.4.6

# Async
aiofiles==23.2.1
asyncio-throttle==1.0.2

# Caching (optional Redis)
redis==5.0.1

# Celery workers (optional)
celery==5.3.6
flower==2.0.1

# Payments
stripe==8.5.0

# Monitoring
sentry-sdk[fastapi]==1.40.0

# Utilities
python-dateutil==2.8.2
pytz==2024.1
ujson==5.9.0
orjson==3.9.15

# Rate limiting
slowapi==0.1.9
limits==3.7.0
