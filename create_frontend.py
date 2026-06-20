"""HTML/CSS/JS Frontend for REXM AI Trading Bot"""

html_content = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>REXM AI - Trading Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #0f1419 0%, #1a1f2e 100%);
            color: #e0e0e0;
            height: 100vh;
            overflow: hidden;
        }

        .container {
            display: flex;
            height: 100vh;
        }

        /* Sidebar */
        .sidebar {
            width: 260px;
            background: #1a1f2e;
            border-right: 1px solid #2d3e4f;
            padding: 20px;
            overflow-y: auto;
        }

        .logo {
            font-size: 24px;
            font-weight: bold;
            color: #00d4ff;
            margin-bottom: 30px;
            text-align: center;
        }

        .nav-menu {
            list-style: none;
        }

        .nav-item {
            padding: 12px 15px;
            margin-bottom: 8px;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.3s ease;
            color: #b0b8c1;
        }

        .nav-item:hover,
        .nav-item.active {
            background: #2d3e4f;
            color: #00d4ff;
            border-left: 3px solid #00d4ff;
        }

        /* Main Content */
        .main-content {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        /* Header */
        .header {
            background: #1a1f2e;
            border-bottom: 1px solid #2d3e4f;
            padding: 20px 30px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .header-title {
            font-size: 28px;
            font-weight: 600;
        }

        .user-info {
            display: flex;
            align-items: center;
            gap: 15px;
        }

        .admin-badge {
            background: #00d4ff;
            color: #0f1419;
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
        }

        .logout-btn {
            background: #ff4444;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
        }

        /* Dashboard Content */
        .dashboard {
            flex: 1;
            overflow-y: auto;
            padding: 30px;
        }

        /* Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .stat-card {
            background: linear-gradient(135deg, #1a1f2e 0%, #2d3e4f 100%);
            padding: 20px;
            border-radius: 10px;
            border: 1px solid #3d4e5f;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
        }

        .stat-label {
            font-size: 12px;
            color: #888;
            text-transform: uppercase;
            margin-bottom: 8px;
            letter-spacing: 1px;
        }

        .stat-value {
            font-size: 28px;
            font-weight: bold;
            color: #00d4ff;
            margin-bottom: 8px;
        }

        .stat-change {
            font-size: 12px;
            color: #4ade80;
        }

        .stat-change.negative {
            color: #f87171;
        }

        /* Cards */
        .card {
            background: linear-gradient(135deg, #1a1f2e 0%, #2d3e4f 100%);
            border: 1px solid #3d4e5f;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
        }

        .card-header {
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        /* Forms */
        .form-group {
            margin-bottom: 15px;
        }

        label {
            display: block;
            margin-bottom: 5px;
            font-size: 12px;
            color: #b0b8c1;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        input, select {
            width: 100%;
            padding: 10px 12px;
            background: #0f1419;
            border: 1px solid #3d4e5f;
            border-radius: 6px;
            color: #e0e0e0;
            font-size: 14px;
        }

        input:focus, select:focus {
            outline: none;
            border-color: #00d4ff;
            box-shadow: 0 0 10px rgba(0, 212, 255, 0.3);
        }

        /* Password input with eye icon */
        .password-input-wrapper {
            position: relative;
        }

        .password-toggle {
            position: absolute;
            right: 12px;
            top: 50%;
            transform: translateY(-50%);
            cursor: pointer;
            color: #888;
        }

        /* Buttons */
        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 6px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .btn-primary {
            background: #00d4ff;
            color: #0f1419;
        }

        .btn-primary:hover {
            background: #00b8cc;
            transform: translateY(-2px);
            box-shadow: 0 8px 20px rgba(0, 212, 255, 0.3);
        }

        .btn-secondary {
            background: #2d3e4f;
            color: #e0e0e0;
            border: 1px solid #3d4e5f;
        }

        .btn-secondary:hover {
            background: #3d4e5f;
        }

        /* Tables */
        table {
            width: 100%;
            border-collapse: collapse;
        }

        th {
            background: #0f1419;
            padding: 12px;
            text-align: left;
            font-size: 12px;
            color: #888;
            text-transform: uppercase;
            border-bottom: 1px solid #3d4e5f;
            letter-spacing: 0.5px;
        }

        td {
            padding: 12px;
            border-bottom: 1px solid #2d3e4f;
        }

        tbody tr:hover {
            background: rgba(0, 212, 255, 0.05);
        }

        /* Status badges */
        .badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }

        .badge-success {
            background: rgba(74, 222, 128, 0.2);
            color: #4ade80;
        }

        .badge-danger {
            background: rgba(248, 113, 113, 0.2);
            color: #f87171;
        }

        .badge-warning {
            background: rgba(251, 191, 36, 0.2);
            color: #fbbf24;
        }

        .badge-info {
            background: rgba(0, 212, 255, 0.2);
            color: #00d4ff;
        }

        /* Login Screen */
        .login-container {
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            background: linear-gradient(135deg, #0f1419 0%, #1a1f2e 100%);
        }

        .login-box {
            background: linear-gradient(135deg, #1a1f2e 0%, #2d3e4f 100%);
            border: 1px solid #3d4e5f;
            border-radius: 10px;
            padding: 40px;
            width: 100%;
            max-width: 400px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
        }

        .login-title {
            text-align: center;
            font-size: 32px;
            font-weight: bold;
            color: #00d4ff;
            margin-bottom: 10px;
        }

        .login-subtitle {
            text-align: center;
            color: #888;
            margin-bottom: 30px;
            font-size: 14px;
        }

        /* Modals */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 0, 0, 0.7);
        }

        .modal.show {
            display: flex;
            justify-content: center;
            align-items: center;
        }

        .modal-content {
            background: linear-gradient(135deg, #1a1f2e 0%, #2d3e4f 100%);
            border: 1px solid #3d4e5f;
            border-radius: 10px;
            padding: 30px;
            width: 90%;
            max-width: 500px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
        }

        .close-modal {
            float: right;
            font-size: 24px;
            cursor: pointer;
            color: #888;
        }

        .close-modal:hover {
            color: #00d4ff;
        }

        /* Responsive */
        @media (max-width: 768px) {
            .container {
                flex-direction: column;
            }

            .sidebar {
                width: 100%;
                height: auto;
            }

            .stats-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>

<!-- Login Screen -->
<div id="loginScreen" class="login-container">
    <div class="login-box">
        <div class="login-title">REXM AI</div>
        <div class="login-subtitle">Trading Bot Administration</div>
        <form id="loginForm">
            <div class="form-group">
                <label>Email Address</label>
                <input type="email" id="adminEmail" placeholder="Enter admin email" required>
            </div>
            <div class="form-group">
                <label>Password</label>
                <div class="password-input-wrapper">
                    <input type="password" id="adminPassword" placeholder="Enter password" required>
                    <span class="password-toggle" onclick="togglePassword()">👁️</span>
                </div>
            </div>
            <button type="submit" class="btn btn-primary" style="width: 100%; margin-top: 20px;">Login</button>
        </form>
    </div>
</div>

<!-- Dashboard -->
<div id="dashboardScreen" style="display: none;">
    <div class="container">
        <!-- Sidebar -->
        <div class="sidebar">
            <div class="logo">🤖 REXM AI</div>
            <ul class="nav-menu">
                <li class="nav-item active" onclick="showSection('dashboard')">📊 Dashboard</li>
                <li class="nav-item" onclick="showSection('settings')">⚙️ Settings</li>
                <li class="nav-item" onclick="showSection('trades')">📈 Trades</li>
                <li class="nav-item" onclick="showSection('portfolio')">💼 Portfolio</li>
                <li class="nav-item" onclick="showSection('users')">👥 Users</li>
                <li class="nav-item" onclick="showSection('support')">❓ Support</li>
                <li class="nav-item" onclick="logout()" style="margin-top: 30px; color: #f87171;">🚪 Logout</li>
            </ul>
        </div>

        <!-- Main Content -->
        <div class="main-content">
            <!-- Header -->
            <div class="header">
                <div class="header-title" id="sectionTitle">Dashboard</div>
                <div class="user-info">
                    <span class="admin-badge">👤 ADMIN</span>
                    <span id="adminEmailDisplay">eestradingmachine@gmail.com</span>
                </div>
            </div>

            <!-- Dashboard Content -->
            <div class="dashboard">
                <!-- Dashboard Section -->
                <div id="dashboardSection" class="section-content">
                    <h2>Trading Overview</h2>
                    <div class="stats-grid">
                        <div class="stat-card">
                            <div class="stat-label">Total Capital</div>
                            <div class="stat-value">$5,000</div>
                            <div class="stat-change">+ 12.5%</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">Current Balance</div>
                            <div class="stat-value">$5,625</div>
                            <div class="stat-change">+$625</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">Open Positions</div>
                            <div class="stat-value">3</div>
                            <div class="stat-change">Healthy</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">Win Rate</div>
                            <div class="stat-value">78%</div>
                            <div class="stat-change positive">12 wins, 3 losses</div>
                        </div>
                    </div>

                    <div class="card">
                        <div class="card-header">
                            Recent Trades
                            <button class="btn btn-secondary" style="padding: 6px 12px; font-size: 12px;">View All</button>
                        </div>
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
                                <tr>
                                    <td>BTC/USDT</td>
                                    <td><span class="badge badge-success">BUY</span></td>
                                    <td>$42,500</td>
                                    <td>$43,200</td>
                                    <td class="stat-change">+$700 (+1.65%)</td>
                                    <td><span class="badge badge-info">OPEN</span></td>
                                </tr>
                                <tr>
                                    <td>ETH/USDT</td>
                                    <td><span class="badge badge-danger">SELL</span></td>
                                    <td>$2,280</td>
                                    <td>$2,250</td>
                                    <td class="stat-change">+$300 (+1.32%)</td>
                                    <td><span class="badge badge-info">OPEN</span></td>
                                </tr>
                                <tr>
                                    <td>ADA/USDT</td>
                                    <td><span class="badge badge-success">BUY</span></td>
                                    <td>$0.98</td>
                                    <td>$0.95</td>
                                    <td class="stat-change negative">-$150 (-3.06%)</td>
                                    <td><span class="badge badge-warning">AT RISK</span></td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- Settings Section -->
                <div id="settingsSection" class="section-content" style="display: none;">
                    <h2>Configuration Settings</h2>
                    <div class="card">
                        <div class="card-header">Binance API Configuration</div>
                        <form id="apiSettingsForm">
                            <div class="form-group">
                                <label>Binance API Key</label>
                                <input type="text" id="apiKey" placeholder="Enter your Binance API key">
                            </div>
                            <div class="form-group">
                                <label>Binance Secret Key</label>
                                <div class="password-input-wrapper">
                                    <input type="password" id="secretKey" placeholder="Enter your Binance secret key">
                                    <span class="password-toggle" onclick="toggleSecretKey()">👁️</span>
                                </div>
                            </div>
                            <div class="form-group">
                                <label>Public IPv4 Address</label>
                                <input type="text" id="ipAddress" placeholder="e.g., 13.114.15.219">
                            </div>
                            <div class="form-group">
                                <label>Testnet Mode</label>
                                <input type="checkbox" id="testnetMode" checked>
                            </div>
                            <button type="submit" class="btn btn-primary">Save API Settings</button>
                        </form>
                    </div>

                    <div class="card">
                        <div class="card-header">Trading Parameters</div>
                        <form id="tradingSettingsForm">
                            <div class="form-group">
                                <label>Capital Size (USDT)</label>
                                <input type="number" id="capitalSize" min="5" max="1000" value="100" placeholder="5 - 1000 USDT">
                            </div>
                            <div class="form-group">
                                <label>Profit Target (%)</label>
                                <input type="number" id="profitTarget" min="0.8" max="50" step="0.1" value="5" placeholder="0.8 - 50%">
                            </div>
                            <div class="form-group">
                                <label>Max Loss Per Trade (%)</label>
                                <input type="number" id="maxLoss" min="0.1" max="10" step="0.1" value="2" placeholder="Max loss percentage">
                            </div>
                            <div class="form-group">
                                <label>Number of Bot Instances</label>
                                <input type="number" id="botInstances" min="1" max="5" value="2">
                            </div>
                            <div class="form-group">
                                <label>Enabled Strategies</label>
                                <select id="strategies" multiple>
                                    <option selected>Market Making</option>
                                    <option selected>Mean Reversion</option>
                                    <option selected>Momentum Trading</option>
                                    <option selected>Cross Exchange Arbitrage</option>
                                    <option>Triangular Arbitrage</option>
                                </select>
                            </div>
                            <button type="submit" class="btn btn-primary">Save Trading Settings</button>
                        </form>
                    </div>
                </div>

                <!-- Trades Section -->
                <div id="tradesSection" class="section-content" style="display: none;">
                    <h2>Trade History</h2>
                    <div class="card">
                        <table>
                            <thead>
                                <tr>
                                    <th>Date</th>
                                    <th>Symbol</th>
                                    <th>Side</th>
                                    <th>Quantity</th>
                                    <th>Entry Price</th>
                                    <th>Exit Price</th>
                                    <th>P&L</th>
                                    <th>Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td>2026-06-20</td>
                                    <td>BTC/USDT</td>
                                    <td><span class="badge badge-success">BUY</span></td>
                                    <td>0.05</td>
                                    <td>$42,000</td>
                                    <td>$42,500</td>
                                    <td class="stat-change">+$25</td>
                                    <td><span class="badge badge-success">CLOSED</span></td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- Portfolio Section -->
                <div id="portfolioSection" class="section-content" style="display: none;">
                    <h2>Portfolio Analysis</h2>
                    <div class="stats-grid">
                        <div class="stat-card">
                            <div class="stat-label">Sharpe Ratio</div>
                            <div class="stat-value">2.45</div>
                            <div class="stat-change">Excellent</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">Max Drawdown</div>
                            <div class="stat-value">-8.5%</div>
                            <div class="stat-change">Within limits</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">Sortino Ratio</div>
                            <div class="stat-value">3.12</div>
                            <div class="stat-change">Strong</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">Profit Factor</div>
                            <div class="stat-value">2.8</div>
                            <div class="stat-change">Healthy</div>
                        </div>
                    </div>
                </div>

                <!-- Users Section -->
                <div id="usersSection" class="section-content" style="display: none;">
                    <h2>User Management</h2>
                    <div class="card">
                        <table>
                            <thead>
                                <tr>
                                    <th>Username</th>
                                    <th>Email</th>
                                    <th>Capital</th>
                                    <th>Status</th>
                                    <th>2FA</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td>trader_001</td>
                                    <td>trader@example.com</td>
                                    <td>$500</td>
                                    <td><span class="badge badge-success">Active</span></td>
                                    <td><span class="badge badge-success">Enabled</span></td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- Support Section -->
                <div id="supportSection" class="section-content" style="display: none;">
                    <h2>Support & Help</h2>
                    <div class="card">
                        <h3>REXM AI Trading Bot Support</h3>
                        <p style="margin-top: 15px; line-height: 1.6;">
                            <strong>Admin Contact:</strong> eestradingmachine@gmail.com<br><br>
                            <strong>Documentation:</strong> See README.md<br><br>
                            <strong>API Status:</strong> ✅ Operational<br><br>
                            <strong>Database:</strong> ✅ Connected<br><br>
                            <strong>System Uptime:</strong> 99.9%
                        </p>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
    const API_BASE_URL = 'http://localhost:8000/api';
    let authToken = null;

    // Toggle password visibility
    function togglePassword() {
        const input = document.getElementById('adminPassword');
        input.type = input.type === 'password' ? 'text' : 'password';
    }

    function toggleSecretKey() {
        const input = document.getElementById('secretKey');
        input.type = input.type === 'password' ? 'text' : 'password';
    }

    // Login
    document.getElementById('loginForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('adminEmail').value;
        const password = document.getElementById('adminPassword').value;

        try {
            const response = await fetch(`${API_BASE_URL}/auth/admin/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password })
            });

            if (response.ok) {
                const data = await response.json();
                authToken = data.access_token;
                localStorage.setItem('authToken', authToken);
                document.getElementById('loginScreen').style.display = 'none';
                document.getElementById('dashboardScreen').style.display = 'block';
                document.getElementById('adminEmailDisplay').textContent = email;
                showNotification('✅ Login successful!');
            } else {
                showNotification('❌ Invalid credentials', 'error');
            }
        } catch (error) {
            showNotification('❌ Connection error', 'error');
            console.error(error);
        }
    });

    // Show section
    function showSection(sectionName) {
        // Hide all sections
        document.querySelectorAll('.section-content').forEach(el => {
            el.style.display = 'none';
        });

        // Remove active class
        document.querySelectorAll('.nav-item').forEach(el => {
            el.classList.remove('active');
        });

        // Show selected section
        const sectionMap = {
            'dashboard': ['dashboardSection', 'Dashboard'],
            'settings': ['settingsSection', 'Settings'],
            'trades': ['tradesSection', 'Trade History'],
            'portfolio': ['portfolioSection', 'Portfolio Analysis'],
            'users': ['usersSection', 'User Management'],
            'support': ['supportSection', 'Support & Help']
        };

        const [sectionId, title] = sectionMap[sectionName];
        document.getElementById(sectionId).style.display = 'block';
        document.getElementById('sectionTitle').textContent = title;

        // Mark nav item as active
        event.target.classList.add('active');
    }

    // Logout
    function logout() {
        localStorage.removeItem('authToken');
        authToken = null;
        document.getElementById('dashboardScreen').style.display = 'none';
        document.getElementById('loginScreen').style.display = 'flex';
        document.getElementById('loginForm').reset();
    }

    // Show notification
    function showNotification(message, type = 'success') {
        alert(message);
    }

    // Check if already logged in
    window.addEventListener('load', () => {
        authToken = localStorage.getItem('authToken');
        if (authToken) {
            document.getElementById('loginScreen').style.display = 'none';
            document.getElementById('dashboardScreen').style.display = 'block';
        }
    });

    // Handle API settings form
    document.getElementById('apiSettingsForm')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const settings = {
            binance_api_key: document.getElementById('apiKey').value,
            binance_secret_key: document.getElementById('secretKey').value,
            assigned_ipv4: document.getElementById('ipAddress').value,
            binance_testnet: document.getElementById('testnetMode').checked
        };

        try {
            const response = await fetch(`${API_BASE_URL}/settings/api-settings`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${authToken}`
                },
                body: JSON.stringify(settings)
            });

            if (response.ok) {
                showNotification('✅ API settings saved successfully!');
            } else {
                showNotification('❌ Failed to save API settings', 'error');
            }
        } catch (error) {
            showNotification('❌ Connection error', 'error');
            console.error(error);
        }
    });

    // Handle trading settings form
    document.getElementById('tradingSettingsForm')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const settings = {
            capital_size_usdt: parseFloat(document.getElementById('capitalSize').value),
            profit_target_percent: parseFloat(document.getElementById('profitTarget').value),
            max_loss_per_trade_percent: parseFloat(document.getElementById('maxLoss').value),
            bot_instances: parseInt(document.getElementById('botInstances').value),
            enabled_strategies: Array.from(document.getElementById('strategies').selectedOptions).map(o => o.value)
        };

        try {
            const response = await fetch(`${API_BASE_URL}/settings/trading-settings`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${authToken}`
                },
                body: JSON.stringify(settings)
            });

            if (response.ok) {
                showNotification('✅ Trading settings saved successfully!');
            } else {
                showNotification('❌ Failed to save trading settings', 'error');
            }
        } catch (error) {
            showNotification('❌ Connection error', 'error');
            console.error(error);
        }
    });
</script>

</body>
</html>
'''

if __name__ == '__main__':
    with open('frontend.html', 'w') as f:
        f.write(html_content)
    print('✅ Frontend created: frontend.html')
