import React, { useState, useEffect } from 'react';
import axios from 'axios';
import Dashboard from './components/Dashboard';
import Settings from './components/Settings';
import Trades from './components/Trades';
import Portfolio from './components/Portfolio';
import Trading from './components/Trading';
import Login from './components/Login';
import './App.css';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000/api';

function App() {
  const [currentPage, setCurrentPage] = useState('dashboard');
  const [authToken, setAuthToken] = useState(localStorage.getItem('authToken'));
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (authToken) {
      fetchUserProfile();
    }
  }, [authToken]);

  const fetchUserProfile = async () => {
    try {
      const response = await axios.get(`${API_URL}/auth/profile`, {
        headers: { Authorization: `Bearer ${authToken}` }
      });
      setUser(response.data);
    } catch (error) {
      console.error('Error fetching profile:', error);
      handleLogout();
    }
  };

  const handleLogin = (token) => {
    setAuthToken(token);
    localStorage.setItem('authToken', token);
  };

  const handleLogout = () => {
    setAuthToken(null);
    setUser(null);
    localStorage.removeItem('authToken');
    setCurrentPage('dashboard');
  };

  if (!authToken) {
    return <Login onLogin={handleLogin} />;
  }

  return (
    <div className="app-container">
      <nav className="sidebar">
        <div className="logo">🤖 REXM AI</div>
        <ul className="nav-menu">
          <li className={currentPage === 'dashboard' ? 'active' : ''} onClick={() => setCurrentPage('dashboard')}>📊 Dashboard</li>
          <li className={currentPage === 'trading' ? 'active' : ''} onClick={() => setCurrentPage('trading')}>💹 Trading</li>
          <li className={currentPage === 'trades' ? 'active' : ''} onClick={() => setCurrentPage('trades')}>📈 Trades</li>
          <li className={currentPage === 'portfolio' ? 'active' : ''} onClick={() => setCurrentPage('portfolio')}>💼 Portfolio</li>
          <li className={currentPage === 'settings' ? 'active' : ''} onClick={() => setCurrentPage('settings')}>⚙️ Settings</li>
          <li onClick={handleLogout} style={{ marginTop: '30px', color: '#f87171' }}>🚪 Logout</li>
        </ul>
      </nav>

      <div className="main-content">
        <header className="header">
          <h1>{currentPage.charAt(0).toUpperCase() + currentPage.slice(1)}</h1>
          <div className="user-info">
            <span className="badge">👤 ADMIN</span>
            <span>{user?.email}</span>
          </div>
        </header>

        <main className="content">
          {currentPage === 'dashboard' && <Dashboard authToken={authToken} />}
          {currentPage === 'trading' && <Trading authToken={authToken} />}
          {currentPage === 'trades' && <Trades authToken={authToken} />}
          {currentPage === 'portfolio' && <Portfolio authToken={authToken} />}
          {currentPage === 'settings' && <Settings authToken={authToken} />}
        </main>
      </div>
    </div>
  );
}

export default App;
