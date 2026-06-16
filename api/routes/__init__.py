from .exchange import router as exchange_router
from .bots import router as bots_router
from .analytics import router as analytics_router
from .users import router as users_router

# Alias for main.py
exchange = type('obj', (object,), {'router': exchange_router})
bots = type('obj', (object,), {'router': bots_router})
analytics = type('obj', (object,), {'router': analytics_router})
users = type('obj', (object,), {'router': users_router})
