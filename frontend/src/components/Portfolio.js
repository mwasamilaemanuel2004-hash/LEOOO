import React, { useEffect, useState } from 'react';
import axios from 'axios';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000/api';

function Portfolio({ authToken }) {
  const [portfolio, setPortfolio] = useState(null);
  const [positions, setPositions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchPortfolioData();
  }, [authToken]);

  const fetchPortfolioData = async () => {
    try {
      const [portfolioRes, positionsRes] = await Promise.all([
        axios.get(`${API_URL}/portfolio/overview`, {
          headers: { Authorization: `Bearer ${authToken}` }
        }),
        axios.get(`${API_URL}/trading/positions`, {
          headers: { Authorization: `Bearer ${authToken}` }
        })
      ]);

      setPortfolio(portfolioRes.data);
      setPositions(positionsRes.data.positions);
    } catch (error) {
      console.error('Error fetching portfolio:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <div>Loading...</div>;

  return (
    <div className="portfolio">
      {portfolio && (
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-label">Total Capital</div>
            <div className="stat-value">${portfolio.total_capital?.toFixed(2) || 0}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Total P&L</div>
            <div className={`stat-value ${portfolio.total_pnl >= 0 ? 'positive' : 'negative'}`}>
              ${portfolio.total_pnl?.toFixed(2) || 0}
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Win Rate</div>
            <div className="stat-value">{portfolio.win_rate?.toFixed(1) || 0}%</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Sharpe Ratio</div>
            <div className="stat-value">{portfolio.sharpe_ratio?.toFixed(2) || 0}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Max Drawdown</div>
            <div className="stat-value negative">{portfolio.max_drawdown?.toFixed(2) || 0}%</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Profit Factor</div>
            <div className="stat-value">{portfolio.profit_factor?.toFixed(2) || 0}</div>
          </div>
        </div>
      )}

      <div className="card">
        <h2>Open Positions</h2>
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Side</th>
              <th>Quantity</th>
              <th>Entry Price</th>
              <th>Current Price</th>
              <th>Unrealized P&L</th>
              <th>SL/TP</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((pos) => (
              <tr key={pos.id}>
                <td>{pos.symbol}</td>
                <td><span className={`badge badge-${pos.side === 'LONG' ? 'success' : 'danger'}`}>{pos.side}</span></td>
                <td>{pos.quantity}</td>
                <td>${pos.entry_price}</td>
                <td>${pos.current_price}</td>
                <td className={pos.unrealized_pnl >= 0 ? 'positive' : 'negative'}>{pos.unrealized_pnl_percent?.toFixed(2)}%</td>
                <td>${pos.stop_loss} / ${pos.take_profit}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default Portfolio;
