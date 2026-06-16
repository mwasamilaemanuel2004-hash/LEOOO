import asyncio
import time
from typing import List, Dict, Optional
from services.exchange_service import exchange_service
from core.database import db
import structlog

log = structlog.get_logger("arbitrage_engine")

class ArbitrageEngine:
    """
    Institutional AI Arbitrage Engine supporting multiple strategies:
    - Spatial (Cross-exchange)
    - Triangular (Intra-exchange)
    - Funding Rate (Spot-Perp)
    - Basis (Spot-Futures)
    """

    def __init__(self):
        self.min_spread_spatial = 0.005 # 0.5%
        self.min_spread_triangular = 0.003 # 0.3%
        self.running = False

    async def find_spatial_opportunities(self, symbols: List[str], exchanges: List[str], user_id: str):
        """
        Scan multiple exchanges for price discrepancies on the same symbols.
        """
        opportunities = []
        for symbol in symbols:
            opp = await self._check_symbol_spatial(symbol, exchanges, user_id)
            if opp:
                opportunities.append(opp)
        return opportunities

    async def _check_symbol_spatial(self, symbol: str, exchanges: List[str], user_id: str) -> Optional[Dict]:
        prices = []
        for ex_id in exchanges:
            try:
                client = await exchange_service.get_client(user_id, ex_id)
                ticker = await client.fetch_ticker(symbol)
                prices.append({
                    "exchange": ex_id,
                    "ask": ticker["ask"],
                    "bid": ticker["bid"],
                    "timestamp": time.time()
                })
            except Exception as e:
                log.warn("fetch_ticker_failed", exchange=ex_id, symbol=symbol, error=str(e))

        if len(prices) < 2: return None

        # Buy on lowest ask, sell on highest bid
        lowest_ask = min(prices, key=lambda x: x["ask"])
        highest_bid = max(prices, key=lambda x: x["bid"])

        spread = (highest_bid["bid"] - lowest_ask["ask"]) / lowest_ask["ask"]

        if spread > self.min_spread_spatial:
            return {
                "strategy": "spatial_arbitrage",
                "symbol": symbol,
                "buy_exchange": lowest_ask["exchange"],
                "sell_exchange": highest_bid["exchange"],
                "buy_price": lowest_ask["ask"],
                "sell_price": highest_bid["bid"],
                "gross_spread_pct": spread * 100,
                "expected_net_profit_pct": (spread - 0.002) * 100 # Approx fees
            }
        return None

    async def find_triangular_opportunities(self, exchange_id: str, user_id: str):
        """
        Scan for triangular arbitrage within a single exchange.
        Example: BTC/USDT -> ETH/BTC -> ETH/USDT
        """
        # Simplified example
        try:
            client = await exchange_service.get_client(user_id, exchange_id)
            # In a real scenario, we'd pre-calculate valid triangles
            # For brevity, let's assume a fixed triangle: BTC-ETH-USDT
            tickers = await client.fetch_tickers(['BTC/USDT', 'ETH/BTC', 'ETH/USDT'])

            # 1. Start with 1000 USDT -> buy BTC
            # 2. Sell BTC for ETH
            # 3. Sell ETH for USDT

            p1 = tickers['BTC/USDT']['ask']
            p2 = tickers['ETH/BTC']['ask']
            p3 = tickers['ETH/USDT']['bid']

            # Result of 1 USDT: (1 / p1) / p2 * p3
            final_usdt = (1.0 / p1) / p2 * p3
            profit_pct = (final_usdt - 1.0) * 100

            if profit_pct > (self.min_spread_triangular * 100):
                return {
                    "strategy": "triangular_arbitrage",
                    "exchange": exchange_id,
                    "path": "USDT -> BTC -> ETH -> USDT",
                    "profit_pct": profit_pct
                }
        except Exception as e:
            log.error("tri_arb_failed", exchange=exchange_id, error=str(e))
        return None

    async def find_funding_opportunities(self, symbols: List[str], exchange_id: str, user_id: str):
        """
        Scan for high funding rates to execute spot-perp arbitrage.
        Long Spot, Short Perp when funding is positive.
        """
        ops = []
        try:
            client = await exchange_service.get_client(user_id, exchange_id)
            funding_rates = await client.fetch_funding_rates(symbols)
            for symbol, rate in funding_rates.items():
                # rate is usually for 8h, multiply by 3 for daily
                daily_rate = rate['fundingRate'] * 3 * 100
                if daily_rate > 0.05: # > 0.05% daily
                    ops.append({
                        "strategy": "funding_arbitrage",
                        "symbol": symbol,
                        "funding_rate_8h_pct": rate['fundingRate'] * 100,
                        "daily_est_pct": daily_rate
                    })
        except Exception as e:
            log.error("funding_arb_scan_failed", exchange=exchange_id, error=str(e))
        return ops

arbitrage_engine = ArbitrageEngine()
