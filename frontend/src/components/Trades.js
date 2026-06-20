import React, { useEffect, useState } from 'react';
import axios from 'axios';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000/api';

function Trades({ authToken }) {
  const [trades, setTrades] = useState([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);

  useEffect(() => {
    fetchTrades();
  }, [authToken, page]);

  const fetchTrades = async () => {
    try {
      const response = await axios.get(`${API_URL}/trading/trades?page=${page}&per_page=20`, {
        headers: { Authorization: `Bearer ${authToken}` }
      });
      setTrades(response.data.trades);
    } catch (error) {
      console.error('Error fetching trades:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <div>Loading...</div>;

  return (
    <div className="trades">
      <div className="card">
        <h2>Trade History</h2>
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Symbol</th>
              <th>Side</th>
              <th>Entry Price</th>
              <th>Exit Price</th>
              <th>Quantity</th>
              <th>P&L</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((trade) => (
              <tr key={trade.id}>
                <td>{new Date(trade.entry_time).toLocaleDateString()}</td>
                <td>{trade.symbol}</td>
                <td><span className={`badge badge-${trade.side === 'BUY' ? 'success' : 'danger'}`}>{trade.side}</span></td>
                <td>${trade.entry_price}</td>
                <td>${trade.exit_price || '-'}</td>
                <td>{trade.entry_quantity}</td>
                <td className={trade.pnl >= 0 ? 'positive' : 'negative'}>{trade.pnl_percent?.toFixed(2)}%</td>
                <td><span className={`badge badge-${trade.status === 'OPEN' ? 'info' : 'success'}`}>{trade.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default Trades;
