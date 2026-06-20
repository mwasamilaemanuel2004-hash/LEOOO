import React, { useState, useEffect } from 'react';
import axios from 'axios';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000/api';

function Settings({ authToken }) {
  const [apiSettings, setApiSettings] = useState({
    binance_api_key: '',
    binance_secret_key: '',
    binance_testnet: true,
    assigned_ipv4: ''
  });

  const [tradingSettings, setTradingSettings] = useState({
    capital_size_usdt: 100,
    profit_target_percent: 5,
    max_loss_per_trade_percent: 2,
    bot_instances: 2,
    enabled_strategies: []
  });

  const [showSecretKey, setShowSecretKey] = useState(false);
  const [savedMessage, setSavedMessage] = useState('');

  useEffect(() => {
    fetchSettings();
  }, [authToken]);

  const fetchSettings = async () => {
    try {
      const [apiRes, tradingRes] = await Promise.all([
        axios.get(`${API_URL}/settings/api-settings`, {
          headers: { Authorization: `Bearer ${authToken}` }
        }).catch(() => null),
        axios.get(`${API_URL}/settings/trading-settings`, {
          headers: { Authorization: `Bearer ${authToken}` }
        }).catch(() => null)
      ]);

      if (apiRes?.data) setApiSettings(apiRes.data);
      if (tradingRes?.data) setTradingSettings(tradingRes.data);
    } catch (error) {
      console.error('Error fetching settings:', error);
    }
  };

  const handleApiSettingsSave = async () => {
    try {
      await axios.post(`${API_URL}/settings/api-settings`, apiSettings, {
        headers: { Authorization: `Bearer ${authToken}` }
      });
      setSavedMessage('✅ API settings saved!');
      setTimeout(() => setSavedMessage(''), 3000);
    } catch (error) {
      setSavedMessage('❌ Error saving API settings');
    }
  };

  const handleTradingSettingsSave = async () => {
    try {
      await axios.post(`${API_URL}/settings/trading-settings`, tradingSettings, {
        headers: { Authorization: `Bearer ${authToken}` }
      });
      setSavedMessage('✅ Trading settings saved!');
      setTimeout(() => setSavedMessage(''), 3000);
    } catch (error) {
      setSavedMessage('❌ Error saving trading settings');
    }
  };

  return (
    <div className="settings">
      {savedMessage && <div className="message">{savedMessage}</div>}

      <div className="card">
        <h2>🔐 Binance API Configuration</h2>
        <div className="form-group">
          <label>API Key</label>
          <input
            type="text"
            value={apiSettings.binance_api_key || ''}
            onChange={(e) => setApiSettings({ ...apiSettings, binance_api_key: e.target.value })}
            placeholder="Enter Binance API key"
          />
        </div>
        <div className="form-group">
          <label>Secret Key</label>
          <div className="password-input">
            <input
              type={showSecretKey ? 'text' : 'password'}
              value={apiSettings.binance_secret_key || ''}
              onChange={(e) => setApiSettings({ ...apiSettings, binance_secret_key: e.target.value })}
              placeholder="Enter Binance secret key"
            />
            <span onClick={() => setShowSecretKey(!showSecretKey)}>👁️</span>
          </div>
        </div>
        <div className="form-group">
          <label>Public IPv4 Address</label>
          <input
            type="text"
            value={apiSettings.assigned_ipv4 || ''}
            onChange={(e) => setApiSettings({ ...apiSettings, assigned_ipv4: e.target.value })}
            placeholder="e.g., 13.114.15.219"
          />
        </div>
        <div className="form-group">
          <label>
            <input
              type="checkbox"
              checked={apiSettings.binance_testnet}
              onChange={(e) => setApiSettings({ ...apiSettings, binance_testnet: e.target.checked })}
            />
            Use Testnet
          </label>
        </div>
        <button onClick={handleApiSettingsSave} className="btn-primary">Save API Settings</button>
      </div>

      <div className="card">
        <h2>📊 Trading Configuration</h2>
        <div className="form-group">
          <label>Capital Size (USDT)</label>
          <input
            type="number"
            min="5"
            max="1000"
            value={tradingSettings.capital_size_usdt}
            onChange={(e) => setTradingSettings({ ...tradingSettings, capital_size_usdt: parseFloat(e.target.value) })}
          />
          <small>5 - 1000 USDT</small>
        </div>
        <div className="form-group">
          <label>Profit Target (%)</label>
          <input
            type="number"
            min="0.8"
            max="50"
            step="0.1"
            value={tradingSettings.profit_target_percent}
            onChange={(e) => setTradingSettings({ ...tradingSettings, profit_target_percent: parseFloat(e.target.value) })}
          />
          <small>0.8 - 50%</small>
        </div>
        <div className="form-group">
          <label>Max Loss Per Trade (%)</label>
          <input
            type="number"
            min="0.1"
            max="10"
            step="0.1"
            value={tradingSettings.max_loss_per_trade_percent}
            onChange={(e) => setTradingSettings({ ...tradingSettings, max_loss_per_trade_percent: parseFloat(e.target.value) })}
          />
        </div>
        <div className="form-group">
          <label>Bot Instances</label>
          <input
            type="number"
            min="1"
            max="5"
            value={tradingSettings.bot_instances}
            onChange={(e) => setTradingSettings({ ...tradingSettings, bot_instances: parseInt(e.target.value) })}
          />
        </div>
        <button onClick={handleTradingSettingsSave} className="btn-primary">Save Trading Settings</button>
      </div>
    </div>
  );
}

export default Settings;
