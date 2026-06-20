import React, { useState } from 'react';
import axios from 'axios';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000/api';

function Trading({ authToken }) {
  const [formData, setFormData] = useState({
    symbol: 'BTC/USDT',
    side: 'BUY',
    quantity: 0.01,
    entry_price: 43000,
    stop_loss: 42000,
    take_profit: 45000
  });

  const [message, setMessage] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const response = await axios.post(`${API_URL}/trading/execute`, formData, {
        headers: { Authorization: `Bearer ${authToken}` }
      });
      setMessage('✅ Trade executed successfully!');
      setTimeout(() => setMessage(''), 3000);
    } catch (error) {
      setMessage('❌ Error executing trade: ' + error.response?.data?.error);
    }
  };

  return (
    <div className="trading">
      {message && <div className="message">{message}</div>}

      <div className="card">
        <h2>Manual Trade Execution</h2>
        <form onSubmit={handleSubmit}>
          <div className="form-row">
            <div className="form-group">
              <label>Symbol</label>
              <select value={formData.symbol} onChange={(e) => setFormData({ ...formData, symbol: e.target.value })}>
                <option>BTC/USDT</option>
                <option>ETH/USDT</option>
                <option>ADA/USDT</option>
                <option>XRP/USDT</option>
              </select>
            </div>
            <div className="form-group">
              <label>Side</label>
              <select value={formData.side} onChange={(e) => setFormData({ ...formData, side: e.target.value })}>
                <option>BUY</option>
                <option>SELL</option>
              </select>
            </div>
          </div>

          <div className="form-row">
            <div className="form-group">
              <label>Quantity</label>
              <input type="number" step="0.01" value={formData.quantity} onChange={(e) => setFormData({ ...formData, quantity: parseFloat(e.target.value) })} />
            </div>
            <div className="form-group">
              <label>Entry Price</label>
              <input type="number" step="0.01" value={formData.entry_price} onChange={(e) => setFormData({ ...formData, entry_price: parseFloat(e.target.value) })} />
            </div>
          </div>

          <div className="form-row">
            <div className="form-group">
              <label>Stop Loss</label>
              <input type="number" step="0.01" value={formData.stop_loss} onChange={(e) => setFormData({ ...formData, stop_loss: parseFloat(e.target.value) })} />
            </div>
            <div className="form-group">
              <label>Take Profit</label>
              <input type="number" step="0.01" value={formData.take_profit} onChange={(e) => setFormData({ ...formData, take_profit: parseFloat(e.target.value) })} />
            </div>
          </div>

          <button type="submit" className="btn-primary">Execute Trade</button>
        </form>
      </div>
    </div>
  );
}

export default Trading;
