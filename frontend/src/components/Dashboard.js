import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000/api';

function Dashboard({ authToken }) {
  const [stats, setStats] = useState(null);
  const [trades, setTrades] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchDashboardData();
  }, [authToken]);

  const fetchDashboardData = async () => {
    try {
      const [statsRes, tradesRes] = await Promise.all([
        axios.get(`${API_URL}/admin/dashboard`, {
          headers: { Authorization: `Bearer ${authToken}` }
        }),
        axios.get(`${API_URL}/trading/trades?per_page=5`, {
          headers: { Authorization: `Bearer ${authToken}` }
        })
      ]);

      setStats(statsRes.data);
      setTrades(tradesRes.data.trades);
    } catch (error) {
      console.error('Error fetching dashboard:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <div>Loading...</div>;

  return (
    <div className="dashboard">
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-label">Total Users</div>
          <div className="stat-value">{stats?.total_users || 0}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Active Users</div>
          <div className="stat-value">{stats?.active_users || 0}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Total Trades</div>
          <div className="stat-value">{stats?.total_trades || 0}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Total P&L</div>
          <div className="stat-value stat-positive">${(stats?.total_pnl || 0).toFixed(2)}</div>
        </div>
      </div>

      <div className="card">
        <h2>Recent Trades</h2>
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Side</th>
              <th>Entry Price</th>
              <th>Current Price</th>
              <th>P&L</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((trade) => (
              <tr key={trade.id}>
                <td>{trade.symbol}</td>
                <td><span className={`badge badge-${trade.side === 'BUY' ? 'success' : 'danger'}`}>{trade.side}</span></td>
                <td>${trade.entry_price}</td>
                <td>${trade.exit_price || '-'}</td>
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

export default Dashboard;
