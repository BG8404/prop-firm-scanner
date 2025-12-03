// Prop Firm Scanner Dashboard v2 - JavaScript

// State
let webhookCount = 0;
let signalCount = 0;
let signals = [];
let currentTickers = ['MNQ=F', 'MES=F', 'MGC=F'];
let loadedTradeIds = new Set();
let winRateChart = null;
let pnlChart = null;
let apexPnlChart = null;
let apexEquityChart = null;

// Tab management
function switchTab(tabName) {
    document.querySelectorAll('.nav-tab').forEach(tab => tab.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
    
    document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
    document.getElementById(`tab-${tabName}`).classList.add('active');
    
    // Load tab-specific data
    if (tabName === 'analytics') {
        loadAnalytics();
    } else if (tabName === 'apex') {
        loadApexStatus();
    } else if (tabName === 'coach') {
        loadCoachData();
    }
}

// Settings removed for simplicity - values are hardcoded
// Min Confidence: 70%, Min R:R: 1.5:1, Analysis: 5 min, Tickers: MNQ, MES, MGC

function loadSettings() {
    currentTickers = ['MNQ', 'MES', 'MGC'];
}

// Analyze Now - trigger on-demand analysis
async function analyzeNow() {
    const btn = document.getElementById('analyzeBtn');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '⏳ Analyzing...';
    }
    
    try {
        addLog('🔍 Running analysis...', 'info');
        const response = await fetch('/analyze');
        
        if (response.ok) {
            // Open results in new tab or show notification
            window.open('/analyze', '_blank');
            addLog('✅ Analysis complete - check new tab', 'success');
        } else {
            addLog('❌ Analysis failed', 'error');
        }
    } catch (error) {
        addLog('❌ Analysis error: ' + error.message, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '🔍 Analyze Now';
        }
    }
}

// Outcome tracking is now manual - use WIN/LOSS buttons in Trade Journal

// Time update
function updateTime() {
    document.getElementById('currentTime').textContent = new Date().toLocaleTimeString('en-US', { hour12: false, timeZone: 'America/New_York' }) + ' EST';
}

// Logging
function addLog(message, type = 'info') {
    const feed = document.getElementById('liveFeed');
    const time = new Date().toLocaleTimeString('en-US', { hour12: false, timeZone: 'America/New_York' });
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    entry.innerHTML = `<span class="log-time">${time}</span><span class="log-message">${message}</span>`;
    feed.insertBefore(entry, feed.firstChild);
    while (feed.children.length > 50) feed.removeChild(feed.lastChild);
}

function clearLogs() {
    document.getElementById('liveFeed').innerHTML = '';
    addLog('Logs cleared', 'info');
}

// Webhook URL
function copyWebhookUrl() {
    const input = document.getElementById('webhookUrl');
    navigator.clipboard.writeText(input.value).then(() => {
        const btn = document.querySelector('.copy-btn');
        btn.textContent = '✓ Copied!';
        setTimeout(() => btn.textContent = '📋 Copy', 2000);
    });
}

// Set webhook URL based on current location
function setWebhookUrl() {
    const webhookInput = document.getElementById('webhookUrl');
    if (webhookInput) {
        const baseUrl = window.location.origin;
        webhookInput.value = baseUrl + '/webhook';
    }
}

// Manual scan using Yahoo Finance
async function scanAllTickers() {
    const btn = document.getElementById('scanAllBtn');
    const resultsDiv = document.getElementById('scanResults');
    const resultsContent = document.getElementById('scanResultsContent');
    
    btn.textContent = '⏳ Scanning...';
    btn.disabled = true;
    
    try {
        addLog('🔍 Running manual scan...', 'info');
        
        const response = await fetch('/api/scan/all');
        const data = await response.json();
        
        if (data.error) {
            addLog('❌ Scan error: ' + data.error, 'error');
            resultsContent.innerHTML = `<div style="color: #ff6b6b; padding: 12px;">Error: ${data.error}</div>`;
        } else {
            // Show results
            resultsDiv.style.display = 'block';
            
            const signals = data.signals || [];
            const results = data.results || [];
            
            if (signals.length > 0) {
                addLog(`✅ Found ${signals.length} signal(s)!`, 'success');
                
                resultsContent.innerHTML = signals.map(signal => `
                    <div style="background: var(--bg-card); border: 1px solid ${signal.direction === 'long' ? 'rgba(0, 255, 136, 0.3)' : 'rgba(255, 107, 107, 0.3)'}; border-radius: 8px; padding: 16px; margin-bottom: 12px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                            <span style="font-weight: 700; font-size: 1.1em;">${signal.ticker}</span>
                            <span style="background: ${signal.direction === 'long' ? '#00ff88' : '#ff6b6b'}; color: #0a0f1a; padding: 4px 12px; border-radius: 4px; font-weight: 600;">
                                ${signal.direction.toUpperCase()} ${signal.confidence}%
                            </span>
                        </div>
                        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; font-size: 0.9em;">
                            <div><span style="opacity: 0.7;">Entry:</span> <strong>${signal.entry || '--'}</strong></div>
                            <div><span style="opacity: 0.7;">Stop:</span> <strong style="color: #ff6b6b;">${signal.stop || '--'}</strong></div>
                            <div><span style="opacity: 0.7;">Target:</span> <strong style="color: #00ff88;">${signal.target || '--'}</strong></div>
                        </div>
                        <div style="margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border-color); font-size: 0.85em;">
                            <div style="opacity: 0.7;">15m: ${signal.htf_bias} | Entry Type: ${signal.entry_type || 'MTF'}</div>
                        </div>
                    </div>
                `).join('');
            } else {
                addLog('📊 No signals found at this time', 'info');
                
                resultsContent.innerHTML = `
                    <div style="text-align: center; padding: 24px; opacity: 0.7;">
                        <div style="font-size: 2em; margin-bottom: 8px;">📊</div>
                        <div>No signals found - market conditions don't meet criteria</div>
                        <div style="font-size: 0.85em; margin-top: 8px;">
                            ${results.map(r => `${r.ticker}: ${r.htf_bias || 'NEUTRAL'}`).join(' | ')}
                        </div>
                    </div>
                `;
            }
        }
    } catch (error) {
        addLog('❌ Scan failed: ' + error.message, 'error');
        resultsContent.innerHTML = `<div style="color: #ff6b6b; padding: 12px;">Connection error. Is the scanner running?</div>`;
        resultsDiv.style.display = 'block';
    }
    
    btn.textContent = '🚀 Scan All Tickers';
    btn.disabled = false;
}

// Fetch candle history status
async function fetchCandleStatus() {
    try {
        const response = await fetch('/api/candles/status');
        const data = await response.json();
        
        const statusText = document.getElementById('candleStatusText');
        const statusBadge = document.getElementById('candleStatusBadge');
        const detailsDiv = document.getElementById('candleDetails');
        
        if (data.ready_for_analysis) {
            statusText.textContent = `Ready for analysis! ${data.total_candles} candles loaded.`;
            statusBadge.textContent = '✅ Ready';
            statusBadge.className = 'status-badge ok';
        } else if (data.total_candles > 0) {
            const needed = 50 - data.total_candles;
            statusText.textContent = `Building history... ${data.total_candles}/50 candles (~${Math.max(0, needed)} min remaining)`;
            statusBadge.textContent = '⏳ Building';
            statusBadge.className = 'status-badge warning';
        } else {
            statusText.textContent = 'Waiting for TradingView data...';
            statusBadge.textContent = '⏳ Waiting';
            statusBadge.className = 'status-badge warning';
        }
        
        // Show per-ticker breakdown
        let detailsHtml = '';
        for (const [ticker, counts] of Object.entries(data.tickers)) {
            if (counts['1m'] > 0 || ticker === 'MNQ' || ticker === 'MES' || ticker === 'MGC') {
                const pct = Math.min(100, Math.round((counts['1m'] / 50) * 100));
                const color = pct >= 100 ? '#00ff88' : pct >= 50 ? '#ffd93d' : '#ff6b6b';
                detailsHtml += `
                    <div style="background: var(--bg-card); padding: 10px; border-radius: 6px; text-align: center;">
                        <div style="font-weight: 600; margin-bottom: 4px;">${ticker}</div>
                        <div style="font-size: 0.85em; opacity: 0.7;">
                            ${counts['1m']}×1m → ${counts['5m']}×5m, ${counts['15m']}×15m
                        </div>
                        <div style="margin-top: 6px; height: 4px; background: var(--bg-secondary); border-radius: 2px; overflow: hidden;">
                            <div style="height: 100%; width: ${pct}%; background: ${color};"></div>
                        </div>
                    </div>
                `;
            }
        }
        detailsDiv.innerHTML = detailsHtml || '<div style="opacity: 0.5; grid-column: 1/-1; text-align: center;">No data yet</div>';
        
    } catch (error) {
        console.error('Failed to fetch candle status:', error);
    }
}

// Fetch status
async function fetchStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();
        
        const totalCandles = data.candles_stored['1m'] + data.candles_stored['5m'] + data.candles_stored['15m'];
        document.getElementById('candleCount').textContent = totalCandles;
        document.getElementById('webhookCount').textContent = data.webhook_count || 0;
        document.getElementById('signalCount').textContent = data.signal_count || 0;
        
        // Webhook URL is set automatically from current location
        setWebhookUrl();
        
        if (data.recent_signals) {
            data.recent_signals.forEach(signal => {
                if (!signals.find(s => s.time === signal.time && s.ticker === signal.ticker)) {
                    signals.push(signal);
                    addSignal(signal);
                }
            });
        }
    } catch (error) {
        console.error('Failed to fetch status:', error);
    }
}

// Add signal to table
function addSignal(signal) {
    const tbody = document.getElementById('signalsBody');
    if (tbody.querySelector('.empty-state')) tbody.innerHTML = '';

    const confidenceClass = signal.confidence >= 70 ? 'high' : signal.confidence >= 50 ? 'medium' : 'low';
    const directionClass = signal.direction.toLowerCase().replace('_', '');
    const directionIcon = signal.direction === 'long' ? '📈' : signal.direction === 'short' ? '📉' : '⏸️';

    const row = document.createElement('tr');
    row.innerHTML = `
        <td><span class="time-value">${signal.time}</span></td>
        <td><span class="ticker-badge">${signal.ticker}</span></td>
        <td><span class="direction-badge ${directionClass}">${directionIcon} ${signal.direction.toUpperCase()}</span></td>
        <td>${signal.confidence}%</td>
        <td><span class="price-value">${signal.entry || '-'}</span></td>
        <td><span class="price-value">${signal.stop || '-'}</span></td>
        <td><span class="price-value">${signal.target || '-'}</span></td>
        <td><span class="status-badge ${signal.valid ? 'ok' : 'critical'}">${signal.valid ? 'Valid' : 'Rejected'}</span></td>
    `;
    tbody.insertBefore(row, tbody.firstChild);
    while (tbody.children.length > 20) tbody.removeChild(tbody.lastChild);
}

// Fetch performance
async function fetchPerformance() {
    try {
        const response = await fetch('/api/performance');
        const data = await response.json();
        
        const winRate = data.win_rate || 0;
        document.getElementById('winRate').textContent = winRate + '%';
        document.getElementById('winRate').className = `status-value ${winRate >= 50 ? 'green' : 'red'}`;
        document.getElementById('winLossCount').textContent = `${data.wins || 0}W / ${data.losses || 0}L`;
        
        const totalPnl = data.total_pnl || 0;
        document.getElementById('totalPnl').textContent = totalPnl >= 0 ? '+' + totalPnl.toFixed(1) : totalPnl.toFixed(1);
        document.getElementById('totalPnl').className = `status-value ${totalPnl >= 0 ? 'green' : 'red'}`;
        
        if (data.today) {
            const todayPnl = data.today.total_pnl_ticks || 0;
            document.getElementById('todayPnl').textContent = todayPnl >= 0 ? '+' + todayPnl.toFixed(1) : todayPnl.toFixed(1);
            document.getElementById('todayPnl').className = `status-value ${todayPnl >= 0 ? 'green' : 'red'}`;
            document.getElementById('todayRecord').textContent = `${data.today.wins || 0}W / ${data.today.losses || 0}L today`;
        }
        
        if (data.tracking) {
            document.getElementById('trackingCount').textContent = data.tracking.tracking_count || 0;
        }
    } catch (error) {
        console.error('Failed to fetch performance:', error);
    }
}

// Trade journal
async function fetchTradeJournal() {
    try {
        const response = await fetch('/api/trades?limit=15');
        const trades = await response.json();
        if (trades.length === 0) return;
        
        const tbody = document.getElementById('tradeJournalBody');
        if (tbody.querySelector('.empty-state')) tbody.innerHTML = '';
        
        trades.forEach(trade => {
            if (loadedTradeIds.has(trade.id)) {
                const existingRow = document.getElementById(`trade-${trade.id}`);
                if (existingRow && trade.outcome !== 'pending') {
                    existingRow.innerHTML = getTradeRowHTML(trade);
                }
                return;
            }
            
            loadedTradeIds.add(trade.id);
            const row = document.createElement('tr');
            row.id = `trade-${trade.id}`;
            row.innerHTML = getTradeRowHTML(trade);
            if (tbody.firstChild) tbody.insertBefore(row, tbody.firstChild);
            else tbody.appendChild(row);
        });
        
        while (tbody.children.length > 50) {
            const lastChild = tbody.lastChild;
            if (lastChild) {
                const id = lastChild.id?.replace('trade-', '');
                if (id) loadedTradeIds.delete(parseInt(id));
                tbody.removeChild(lastChild);
            }
        }
    } catch (error) {
        console.error('Failed to fetch trade journal:', error);
    }
}

function getTradeRowHTML(trade) {
    const outcomeClass = trade.outcome === 'win' || trade.outcome === 'WIN' ? 'ok' : 
                         trade.outcome === 'loss' || trade.outcome === 'LOSS' ? 'critical' : 'warning';
    const outcomeText = trade.outcome === 'win' || trade.outcome === 'WIN' ? '✅ WIN' : 
                        trade.outcome === 'loss' || trade.outcome === 'LOSS' ? '❌ LOSS' : 
                        trade.outcome === 'expired' || trade.outcome === 'DISCARDED' ? '⏰ EXPIRED' : '⏳ PENDING';
    const pnl = trade.pnl_ticks ? (trade.pnl_ticks >= 0 ? '+' + trade.pnl_ticks.toFixed(1) : trade.pnl_ticks.toFixed(1)) : '--';
    const pnlClass = trade.pnl_ticks >= 0 ? 'green' : 'red';
    const dir = (trade.direction || '').toLowerCase();
    const directionClass = dir === 'long' ? 'long' : dir === 'short' ? 'short' : 'no_trade';
    const directionIcon = dir === 'long' ? '📈' : dir === 'short' ? '📉' : '⏸️';
    
    // Confidence display
    const confidence = trade.confidence || trade.confidence_score || 0;
    const confClass = confidence >= 80 ? 'green' : confidence >= 70 ? 'yellow' : 'red';
    
    // Live direction indicator for pending trades
    let liveIndicator = '--';
    if ((trade.outcome === 'PENDING' || trade.outcome === 'pending') && trade.entry_price && trade.current_price) {
        const entry = parseFloat(trade.entry_price);
        const current = parseFloat(trade.current_price);
        const target = parseFloat(trade.target_price);
        const stop = parseFloat(trade.stop_price);
        
        if (dir === 'long') {
            if (current > entry) {
                const progress = Math.min(((current - entry) / (target - entry)) * 100, 100);
                liveIndicator = `<span style="color: var(--accent-green)">▲ +${(current - entry).toFixed(2)}</span>`;
            } else {
                liveIndicator = `<span style="color: var(--accent-red)">▼ ${(current - entry).toFixed(2)}</span>`;
            }
        } else if (dir === 'short') {
            if (current < entry) {
                liveIndicator = `<span style="color: var(--accent-green)">▼ +${(entry - current).toFixed(2)}</span>`;
            } else {
                liveIndicator = `<span style="color: var(--accent-red)">▲ ${(entry - current).toFixed(2)}</span>`;
            }
        }
    } else if (trade.outcome !== 'PENDING' && trade.outcome !== 'pending') {
        liveIndicator = trade.outcome === 'WIN' || trade.outcome === 'win' ? '✅' : '❌';
    }
    
    return `
        <td><span class="time-value">${trade.timestamp?.split(' ')[1] || '--'}</span></td>
        <td><span class="ticker-badge">${trade.ticker}</span></td>
        <td><span class="direction-badge ${directionClass}">${directionIcon} ${(trade.direction || '').toUpperCase()}</span></td>
        <td><span class="price-value" style="color: var(--accent-${confClass})">${confidence}%</span></td>
        <td><span class="price-value">${trade.entry_price?.toFixed(2) || '--'}</span></td>
        <td><span class="price-value">${trade.stop_price?.toFixed(2) || '--'}</span></td>
        <td><span class="price-value">${trade.target_price?.toFixed(2) || '--'}</span></td>
        <td><span class="status-badge ${outcomeClass}">${outcomeText}</span></td>
        <td>${getTradeActions(trade)}</td>
    `;
}

function getTradeActions(trade) {
    const isPending = trade.outcome === 'PENDING' || trade.outcome === 'pending';
    
    if (isPending) {
        return `
            <div style="display: flex; gap: 4px; justify-content: center;">
                <button onclick="markTrade(${trade.id}, 'WIN')" class="action-btn win-btn" title="Mark as WIN">✅</button>
                <button onclick="markTrade(${trade.id}, 'LOSS')" class="action-btn loss-btn" title="Mark as LOSS">❌</button>
                <button onclick="deleteTrade(${trade.id})" class="action-btn del-btn" title="Delete (didn't take)">🗑️</button>
            </div>
        `;
    } else {
        return `<span style="color: #666; font-size: 0.8em;">--</span>`;
    }
}

async function markTrade(tradeId, outcome) {
    try {
        const response = await fetch(\`/api/trade/\${tradeId}/outcome\`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ outcome: outcome })
        });
        
        if (response.ok) {
            addLog(\`Trade #\${tradeId} marked as \${outcome}\`, outcome === 'WIN' ? 'success' : 'error');
            loadTrades(); // Refresh
        } else {
            addLog(\`Failed to update trade #\${tradeId}\`, 'error');
        }
    } catch (error) {
        addLog(\`Error: \${error.message}\`, 'error');
    }
}

async function deleteTrade(tradeId) {
    if (!confirm('Delete this trade? (You didn\\'t take it)')) return;
    
    try {
        const response = await fetch(\`/api/trade/\${tradeId}\`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            addLog(\`Trade #\${tradeId} deleted\`, 'info');
            loadTrades(); // Refresh
        } else {
            addLog(\`Failed to delete trade #\${tradeId}\`, 'error');
        }
    } catch (error) {
        addLog(\`Error: \${error.message}\`, 'error');
    }
}

// Apex Rules
async function loadApexStatus() {
    try {
        const response = await fetch('/api/apex/status');
        const data = await response.json();
        
        // Daily Loss
        const dailyLoss = data.daily_loss || {};
        const dailyUsedPct = Math.min(dailyLoss.used_pct || 0, 100);
        document.getElementById('dailyLossProgress').style.width = dailyUsedPct + '%';
        document.getElementById('dailyLossProgress').className = `apex-progress-fill ${dailyLoss.status || 'ok'}`;
        document.getElementById('dailyLossValue').textContent = `$${Math.abs(dailyLoss.today_pnl || 0).toFixed(2)} / $${dailyLoss.max_allowed || 0}`;
        document.getElementById('dailyLossPct').textContent = dailyUsedPct.toFixed(1) + '%';
        document.getElementById('dailyLossBadge').className = `status-badge ${dailyLoss.status || 'ok'}`;
        document.getElementById('dailyLossBadge').textContent = (dailyLoss.status || 'ok').toUpperCase();
        
        // Trailing Drawdown
        const drawdown = data.trailing_drawdown || {};
        const ddUsedPct = Math.min(drawdown.used_pct || 0, 100);
        document.getElementById('drawdownProgress').style.width = ddUsedPct + '%';
        document.getElementById('drawdownProgress').className = `apex-progress-fill ${drawdown.status || 'ok'}`;
        document.getElementById('drawdownValue').textContent = `$${(drawdown.current_drawdown || 0).toFixed(2)} / $${drawdown.max_allowed || 0}`;
        document.getElementById('drawdownPct').textContent = ddUsedPct.toFixed(1) + '%';
        document.getElementById('drawdownBadge').className = `status-badge ${drawdown.status || 'ok'}`;
        document.getElementById('drawdownBadge').textContent = (drawdown.status || 'ok').toUpperCase();
        
        // Consistency
        const consistency = data.consistency || {};
        const consistPct = Math.min(consistency.best_day_pct || 0, 100);
        document.getElementById('consistencyProgress').style.width = consistPct + '%';
        document.getElementById('consistencyProgress').className = `apex-progress-fill ${consistency.status || 'ok'}`;
        document.getElementById('consistencyValue').textContent = `${consistPct.toFixed(1)}% / ${consistency.max_day_pct_allowed || 30}%`;
        document.getElementById('consistencyBadge').className = `status-badge ${consistency.status || 'ok'}`;
        document.getElementById('consistencyBadge').textContent = (consistency.status || 'ok').toUpperCase();
        
        // Account info
        const account = data.account || {};
        document.getElementById('apexBalance').textContent = '$' + (account.current_balance || 0).toFixed(2);
        document.getElementById('apexPnl').textContent = (account.total_pnl >= 0 ? '+$' : '-$') + Math.abs(account.total_pnl || 0).toFixed(2);
        document.getElementById('apexPnl').className = account.total_pnl >= 0 ? 'green' : 'red';
        
        // Update Total P&L label
        const totalPnlLabel = document.getElementById('apexTotalPnlLabel');
        if (totalPnlLabel) {
            totalPnlLabel.textContent = (account.total_pnl >= 0 ? '+$' : '-$') + Math.abs(account.total_pnl || 0).toFixed(2);
            totalPnlLabel.style.color = account.total_pnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
        }
        
        // Render Apex charts and tables
        if (data.daily_history) {
            renderApexPnlChart(data.daily_history);
            renderApexEquityChart(data);
            renderApexDailyTable(data);
        }
        
        // Update quick status on main dashboard
        updateApexQuickStatus(data);
        
    } catch (error) {
        console.error('Failed to load Apex status:', error);
    }
}

async function saveApexConfig() {
    const config = {
        account_size: parseFloat(document.getElementById('apexAccountSize').value),
        max_daily_loss: parseFloat(document.getElementById('apexDailyLoss').value),
        max_trailing_drawdown: parseFloat(document.getElementById('apexDrawdown').value),
        initial_balance: parseFloat(document.getElementById('apexAccountSize').value)
    };
    
    try {
        const response = await fetch('/api/apex/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        if (response.ok) {
            addLog('Apex config saved', 'success');
            loadApexStatus();
        }
    } catch (error) {
        addLog('Failed to save Apex config', 'error');
    }
}

async function resetApexState() {
    if (!confirm('Reset Apex tracking state? This will clear all P&L history.')) return;
    
    try {
        const response = await fetch('/api/apex/reset', { method: 'POST' });
        if (response.ok) {
            addLog('Apex state reset', 'warning');
            loadApexStatus();
        }
    } catch (error) {
        addLog('Failed to reset Apex state', 'error');
    }
}

// Render Apex P&L History Chart
function renderApexPnlChart(dailyHistory) {
    const ctx = document.getElementById('apexPnlChart');
    if (!ctx) return;
    
    if (apexPnlChart) apexPnlChart.destroy();
    
    // Sort dates and prepare data
    const dates = Object.keys(dailyHistory).sort();
    const values = dates.map(d => dailyHistory[d]);
    
    if (dates.length === 0) {
        return;
    }
    
    apexPnlChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: dates.map(d => d.slice(5)), // Show MM-DD
            datasets: [{
                label: 'Daily P&L ($)',
                data: values,
                backgroundColor: values.map(v => v >= 0 ? 'rgba(0, 255, 136, 0.7)' : 'rgba(255, 68, 102, 0.7)'),
                borderRadius: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: { 
                    grid: { color: 'rgba(255,255,255,0.05)' }, 
                    ticks: { 
                        color: '#888',
                        callback: (v) => '$' + v
                    } 
                },
                x: { 
                    grid: { color: 'rgba(255,255,255,0.05)' }, 
                    ticks: { color: '#888' } 
                }
            }
        }
    });
}

// Render Apex Equity Chart
function renderApexEquityChart(data) {
    const ctx = document.getElementById('apexEquityChart');
    if (!ctx) return;
    
    if (apexEquityChart) apexEquityChart.destroy();
    
    const dailyHistory = data.daily_history || {};
    const dates = Object.keys(dailyHistory).sort();
    
    if (dates.length === 0) return;
    
    const initialBalance = data.account?.initial_balance || 50000;
    const maxDrawdown = data.config?.max_trailing_drawdown || 2500;
    
    // Calculate cumulative balance and high water mark
    let balance = initialBalance;
    let hwm = initialBalance;
    const balances = [];
    const floors = [];
    const hwms = [];
    
    for (const date of dates) {
        balance += dailyHistory[date];
        if (balance > hwm) hwm = balance;
        balances.push(balance);
        hwms.push(hwm);
        floors.push(hwm - maxDrawdown);
    }
    
    apexEquityChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: dates.map(d => d.slice(5)),
            datasets: [
                {
                    label: 'Balance',
                    data: balances,
                    borderColor: '#00ff88',
                    backgroundColor: 'rgba(0, 255, 136, 0.1)',
                    fill: true,
                    tension: 0.3,
                    borderWidth: 2
                },
                {
                    label: 'High Water Mark',
                    data: hwms,
                    borderColor: '#4488ff',
                    borderDash: [5, 5],
                    tension: 0.3,
                    borderWidth: 1,
                    pointRadius: 0
                },
                {
                    label: 'Drawdown Floor',
                    data: floors,
                    borderColor: '#ff4466',
                    borderDash: [3, 3],
                    tension: 0.3,
                    borderWidth: 1,
                    pointRadius: 0,
                    fill: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { 
                    labels: { color: '#888' },
                    position: 'top'
                }
            },
            scales: {
                y: { 
                    grid: { color: 'rgba(255,255,255,0.05)' }, 
                    ticks: { 
                        color: '#888',
                        callback: (v) => '$' + v.toLocaleString()
                    } 
                },
                x: { 
                    grid: { color: 'rgba(255,255,255,0.05)' }, 
                    ticks: { color: '#888' } 
                }
            }
        }
    });
}

// Render Apex Daily Table
function renderApexDailyTable(data) {
    const tbody = document.getElementById('apexDailyBody');
    if (!tbody) return;
    
    const dailyHistory = data.daily_history || {};
    const dates = Object.keys(dailyHistory).sort().reverse();
    
    if (dates.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5"><div class="empty-state">No trading days recorded</div></td></tr>';
        return;
    }
    
    const maxDailyLoss = data.config?.max_daily_loss || 2500;
    const totalProfit = Object.values(dailyHistory).filter(v => v > 0).reduce((a, b) => a + b, 0);
    
    tbody.innerHTML = dates.slice(0, 14).map(date => {
        const pnl = dailyHistory[date];
        const dailyPct = Math.abs(pnl) / maxDailyLoss * 100;
        const profitPct = totalProfit > 0 && pnl > 0 ? (pnl / totalProfit * 100) : 0;
        
        let statusClass = 'ok';
        let statusText = 'OK';
        
        if (pnl < 0) {
            if (dailyPct >= 100) {
                statusClass = 'critical';
                statusText = 'LIMIT HIT';
            } else if (dailyPct >= 80) {
                statusClass = 'warning';
                statusText = 'WARNING';
            }
        } else if (profitPct > 30) {
            statusClass = 'warning';
            statusText = 'CONSISTENCY';
        }
        
        return `
            <tr>
                <td><span class="time-value">${date}</span></td>
                <td><span class="price-value" style="color: var(--accent-${pnl >= 0 ? 'green' : 'red'})">${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}</span></td>
                <td>${pnl < 0 ? dailyPct.toFixed(1) + '%' : '-'}</td>
                <td>${profitPct > 0 ? profitPct.toFixed(1) + '%' : '-'}</td>
                <td><span class="status-badge ${statusClass}">${statusText}</span></td>
            </tr>
        `;
    }).join('');
}

// Load Market Regime
async function loadMarketRegime() {
    try {
        const response = await fetch('/api/coach/regime');
        const data = await response.json();
        
        const regimeValue = document.getElementById('regimeValue');
        const regimeBadge = document.getElementById('regimeBadge');
        const regimeGuidance = document.getElementById('regimeGuidance');
        
        if (!regimeValue) return;
        
        const regime = data.regime || 'unknown';
        const confidence = Math.round((data.confidence || 0) * 100);
        
        // Format regime name
        const regimeNames = {
            'trending_up': '📈 TRENDING UP',
            'trending_down': '📉 TRENDING DOWN',
            'ranging': '↔️ RANGING',
            'high_volatility': '⚡ HIGH VOLATILITY',
            'low_volatility': '😴 LOW VOLATILITY',
            'choppy': '🌀 CHOPPY',
            'unknown': '❓ ANALYZING'
        };
        
        const regimeColors = {
            'trending_up': '#00ff88',
            'trending_down': '#ff4466',
            'ranging': '#ffaa00',
            'high_volatility': '#ff4466',
            'low_volatility': '#4488ff',
            'choppy': '#ffaa00',
            'unknown': '#888'
        };
        
        regimeValue.textContent = regimeNames[regime] || regime.toUpperCase();
        regimeValue.style.color = regimeColors[regime] || '#888';
        
        regimeBadge.textContent = `${confidence}%`;
        regimeBadge.className = `status-badge ${confidence >= 70 ? 'ok' : 'warning'}`;
        
        // Set guidance
        const guidance = data.guidance || {};
        let guidanceText = data.description || 'Analyzing market conditions...';
        if (guidance.bias && guidance.bias !== 'neutral') {
            guidanceText = `Favor ${guidance.bias.toUpperCase()} trades`;
        }
        regimeGuidance.textContent = guidanceText;
        
    } catch (error) {
        console.error('Failed to load market regime:', error);
    }
}

// Update Apex Quick Status on main dashboard
function updateApexQuickStatus(data) {
    const quickValue = document.getElementById('apexQuickValue');
    const quickBadge = document.getElementById('apexQuickBadge');
    const quickSubtitle = document.getElementById('apexQuickSubtitle');
    
    if (!quickValue) return;
    
    const dailyLoss = data.daily_loss || {};
    const remaining = dailyLoss.remaining || 2500;
    const maxAllowed = dailyLoss.max_allowed || 2500;
    const status = dailyLoss.status || 'ok';
    
    quickValue.textContent = `$${remaining.toFixed(0)} / $${maxAllowed}`;
    quickBadge.textContent = status.toUpperCase();
    quickBadge.className = `status-badge ${status}`;
    
    if (status === 'blocked') {
        quickSubtitle.textContent = '🚫 STOP TRADING';
        quickSubtitle.style.color = 'var(--accent-red)';
    } else if (status === 'warning') {
        quickSubtitle.textContent = '⚠️ Approaching limit!';
        quickSubtitle.style.color = 'var(--accent-yellow)';
    } else {
        quickSubtitle.textContent = 'Daily loss limit remaining';
        quickSubtitle.style.color = 'var(--text-muted)';
    }
}

// Analytics
async function loadAnalytics() {
    try {
        const response = await fetch('/api/analytics');
        const data = await response.json();
        
        // Win rate chart
        const winRateData = data.win_rate_chart || [];
        renderWinRateChart(winRateData);
        
        // P&L chart
        const pnlData = data.pnl_chart || [];
        renderPnlChart(pnlData);
        
        // Ticker performance
        const tickers = data.tickers || {};
        renderTickerTable(tickers.best || [], 'bestTickersBody');
        renderTickerTable(tickers.worst || [], 'worstTickersBody');
        
        // Confidence performance
        const confidence = data.confidence || [];
        renderConfidenceTable(confidence);
        
        // Streaks
        const streaks = data.streaks || {};
        document.getElementById('currentStreak').textContent = 
            `${streaks.current_streak || 0} ${(streaks.current_streak_type || 'n/a').toUpperCase()}`;
        document.getElementById('maxWinStreak').textContent = streaks.max_win_streak || 0;
        document.getElementById('maxLossStreak').textContent = streaks.max_loss_streak || 0;
        
        // Direction performance
        const direction = data.direction || {};
        if (direction.long) {
            document.getElementById('longWinRate').textContent = direction.long.win_rate + '%';
            document.getElementById('longPnl').textContent = direction.long.total_pnl >= 0 ? '+' + direction.long.total_pnl : direction.long.total_pnl;
        }
        if (direction.short) {
            document.getElementById('shortWinRate').textContent = direction.short.win_rate + '%';
            document.getElementById('shortPnl').textContent = direction.short.total_pnl >= 0 ? '+' + direction.short.total_pnl : direction.short.total_pnl;
        }
        
    } catch (error) {
        console.error('Failed to load analytics:', error);
    }
}

function renderWinRateChart(data) {
    const ctx = document.getElementById('winRateChart');
    if (!ctx) return;
    
    if (winRateChart) winRateChart.destroy();
    
    winRateChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.map(d => d.date),
            datasets: [{
                label: 'Win Rate %',
                data: data.map(d => d.win_rate),
                borderColor: '#00ff88',
                backgroundColor: 'rgba(0, 255, 136, 0.1)',
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: { min: 0, max: 100, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#888' } },
                x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#888' } }
            }
        }
    });
}

function renderPnlChart(data) {
    const ctx = document.getElementById('pnlChart');
    if (!ctx) return;
    
    if (pnlChart) pnlChart.destroy();
    
    pnlChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: data.map(d => d.date),
            datasets: [
                {
                    label: 'Daily P&L',
                    data: data.map(d => d.daily_pnl),
                    backgroundColor: data.map(d => d.daily_pnl >= 0 ? 'rgba(0, 255, 136, 0.7)' : 'rgba(255, 68, 102, 0.7)'),
                    borderRadius: 4
                },
                {
                    label: 'Cumulative',
                    data: data.map(d => d.cumulative_pnl),
                    type: 'line',
                    borderColor: '#4488ff',
                    backgroundColor: 'transparent',
                    tension: 0.4,
                    yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: '#888' } }
            },
            scales: {
                y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#888' } },
                y1: { position: 'right', grid: { display: false }, ticks: { color: '#4488ff' } },
                x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#888' } }
            }
        }
    });
}

function renderTickerTable(tickers, bodyId) {
    const tbody = document.getElementById(bodyId);
    if (!tbody) return;
    
    if (tickers.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center">No data</td></tr>';
        return;
    }
    
    tbody.innerHTML = tickers.map(t => `
        <tr>
            <td><span class="ticker-badge">${t.ticker}</span></td>
            <td>${t.total_trades}</td>
            <td>${t.win_rate}%</td>
            <td class="${t.total_pnl >= 0 ? 'green' : 'red'}">${t.total_pnl >= 0 ? '+' : ''}${t.total_pnl}</td>
        </tr>
    `).join('');
}

function renderConfidenceTable(data) {
    const tbody = document.getElementById('confidenceBody');
    if (!tbody) return;
    
    if (data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center">No data</td></tr>';
        return;
    }
    
    tbody.innerHTML = data.map(d => `
        <tr>
            <td>${d.range}%</td>
            <td>${d.total_trades}</td>
            <td>${d.win_rate}%</td>
            <td class="${d.total_pnl >= 0 ? 'green' : 'red'}">${d.total_pnl >= 0 ? '+' : ''}${d.total_pnl}</td>
            <td>${d.avg_pnl >= 0 ? '+' : ''}${d.avg_pnl}</td>
        </tr>
    `).join('');
}

// AI Tuning
async function loadTuningData() {
    try {
        const response = await fetch('/api/tuning/summary');
        const data = await response.json();
        
        const container = document.getElementById('tuningRecommendations');
        
        if (!data.recommendations || data.recommendations.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">🎯</div>
                    <div class="empty-state-text">Current settings appear optimal</div>
                    <div class="empty-state-subtext">AI will recommend changes when performance data suggests improvements</div>
                </div>
            `;
            document.getElementById('applyTuningBtn').disabled = true;
            return;
        }
        
        container.innerHTML = data.recommendations.map(rec => `
            <div class="tuning-recommendation">
                <div class="tuning-recommendation-header">
                    <span class="tuning-recommendation-title">
                        ${rec.type === 'confidence_threshold' ? '🎯' : '📊'} 
                        ${rec.type === 'confidence_threshold' ? 'Confidence Threshold' : 'Risk:Reward'}
                    </span>
                </div>
                <div class="tuning-values">
                    <span class="tuning-old">${rec.current}${rec.type === 'confidence_threshold' ? '%' : ''}</span>
                    <span>→</span>
                    <span class="tuning-new">${rec.recommended}${rec.type === 'confidence_threshold' ? '%' : ''}</span>
                </div>
                <p style="margin-top: 8px; color: var(--text-secondary); font-size: 0.85rem;">${rec.reason}</p>
            </div>
        `).join('');
        
        document.getElementById('applyTuningBtn').disabled = false;
        
        // Confidence analysis
        if (data.confidence_analysis && data.confidence_analysis.status === 'success') {
            const analysis = data.confidence_analysis.analysis || [];
            const tbody = document.getElementById('tuningAnalysisBody');
            if (tbody && analysis.length > 0) {
                tbody.innerHTML = analysis.map(a => `
                    <tr>
                        <td>${a.threshold}%+</td>
                        <td>${a.trades}</td>
                        <td>${a.win_rate}%</td>
                        <td>${a.expectancy >= 0 ? '+' : ''}${a.expectancy}</td>
                        <td>${a.profit_factor}</td>
                    </tr>
                `).join('');
            }
        }
        
        // Load trend
        const trendResponse = await fetch('/api/tuning/trend');
        const trend = await trendResponse.json();
        if (trend.status === 'success') {
            const trendEl = document.getElementById('performanceTrend');
            const trendClass = trend.trend === 'improving' ? 'green' : trend.trend === 'declining' ? 'red' : 'yellow';
            trendEl.innerHTML = `<span class="${trendClass}">${trend.trend.toUpperCase()}</span>`;
        }
        
    } catch (error) {
        console.error('Failed to load tuning data:', error);
    }
}

async function applyTuning() {
    if (!confirm('Apply AI tuning recommendations? This will update your scanner settings.')) return;
    
    try {
        const response = await fetch('/api/tuning/apply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ conservative: true })
        });
        
        const result = await response.json();
        
        if (result.status === 'applied') {
            addLog('AI Tuning applied successfully', 'success');
            loadSettings();
            loadTuningData();
        } else {
            addLog('No changes applied', 'info');
        }
    } catch (error) {
        addLog('Failed to apply tuning', 'error');
    }
}

// ============ AI COACH ============

async function loadCoachData() {
    try {
        // Get suggestions
        const sugResponse = await fetch('/api/coach/suggestions');
        const sugData = await sugResponse.json();
        
        renderCoachSuggestions(sugData.suggestions || []);
        
        // Update stats
        const stats = sugData.stats || {};
        document.getElementById('coachPendingBadge').textContent = `${stats.pending_count || 0} pending`;
        document.getElementById('coachChangesWeek').textContent = stats.changes_this_week || 0;
        
        // Get insights
        const insResponse = await fetch('/api/coach/insights');
        const insights = await insResponse.json();
        
        if (insights.status === 'success' && insights.insights) {
            document.getElementById('coachTotalTrades').textContent = insights.insights.total_trades || '--';
            document.getElementById('coachWinRate').textContent = (insights.insights.overall_win_rate || 0) + '%';
            
            const trend = insights.insights.trend || 'unknown';
            const trendEl = document.getElementById('coachTrend');
            trendEl.textContent = trend.toUpperCase();
            trendEl.className = trend === 'improving' ? 'green' : trend === 'declining' ? 'red' : 'yellow';
        }
        
        // Get history
        const histResponse = await fetch('/api/coach/history?limit=20');
        const history = await histResponse.json();
        renderCoachHistory(history);
        
        // Get prompt status
        loadPromptStatus();
        
    } catch (error) {
        console.error('Failed to load coach data:', error);
    }
}

async function runCoachAnalysis() {
    addLog('Running AI Coach analysis...', 'info');
    
    try {
        const response = await fetch('/api/coach/analyze', { method: 'POST' });
        const result = await response.json();
        
        if (result.status === 'success') {
            addLog(`Analysis complete: ${result.suggestions?.length || 0} suggestions found`, 'success');
            loadCoachData();
        } else {
            addLog(result.message || 'Analysis needs more data', 'warning');
        }
    } catch (error) {
        addLog('Analysis failed: ' + error.message, 'error');
    }
}

function renderCoachSuggestions(suggestions) {
    const container = document.getElementById('coachSuggestions');
    
    if (!suggestions || suggestions.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">✅</div>
                <div class="empty-state-text">No pending suggestions</div>
                <div class="empty-state-subtext">Run analysis to get new recommendations</div>
            </div>
        `;
        return;
    }
    
    container.innerHTML = suggestions.map(s => `
        <div class="suggestion-card" data-id="${s.suggestion_id}">
            <div class="suggestion-header">
                <span class="suggestion-type">${getTypeIcon(s.type)} ${s.type.toUpperCase()}</span>
                <span class="suggestion-confidence">${Math.round((s.confidence || 0) * 100)}% confident</span>
            </div>
            <h3 class="suggestion-title">${s.title}</h3>
            <p class="suggestion-explanation">${s.explanation}</p>
            <div class="suggestion-action">
                <strong>Recommended Action:</strong> ${s.action}
            </div>
            <div class="suggestion-impact">
                <span>📊 Projected Impact:</span> ${s.projected_impact}
                <span style="margin-left: 16px;">📈 Sample: ${s.sample_size} trades</span>
            </div>
            <div class="suggestion-buttons">
                <button class="btn btn-success" onclick="approveSuggestion('${s.suggestion_id}')">✅ Approve & Apply</button>
                <button class="btn btn-outline" onclick="rejectSuggestion('${s.suggestion_id}')">❌ Reject</button>
            </div>
        </div>
    `).join('');
}

function getTypeIcon(type) {
    const icons = {
        'prompt': '📝',
        'filter': '🎚️',
        'pattern': '🔍',
        'timing': '⏰',
        'regime': '🌊'
    };
    return icons[type] || '💡';
}

async function approveSuggestion(id) {
    if (!confirm('Approve this suggestion and apply the change?')) return;
    
    try {
        const response = await fetch(`/api/coach/approve/${id}`, { method: 'POST' });
        const result = await response.json();
        
        if (result.status === 'success') {
            addLog('Suggestion approved and applied', 'success');
            loadCoachData();
            loadSettings();
        } else {
            addLog('Failed to approve: ' + (result.message || 'Unknown error'), 'error');
        }
    } catch (error) {
        addLog('Error approving suggestion', 'error');
    }
}

async function rejectSuggestion(id) {
    const reason = prompt('Optional: Why are you rejecting this suggestion?');
    
    try {
        const response = await fetch(`/api/coach/reject/${id}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reason: reason || '' })
        });
        const result = await response.json();
        
        if (result.status === 'success') {
            addLog('Suggestion rejected', 'info');
            loadCoachData();
        }
    } catch (error) {
        addLog('Error rejecting suggestion', 'error');
    }
}

function renderCoachHistory(history) {
    const tbody = document.getElementById('coachHistoryBody');
    
    if (!history || history.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5"><div class="empty-state">No history yet</div></td></tr>';
        return;
    }
    
    tbody.innerHTML = history.map(h => {
        const statusClass = h.status === 'approved' ? 'ok' : h.status === 'rejected' ? 'critical' : 'warning';
        const statusText = h.status === 'approved' ? '✅ Approved' : h.status === 'rejected' ? '❌ Rejected' : '↩️ Undone';
        const date = h.reviewed_at ? new Date(h.reviewed_at).toLocaleDateString() : '--';
        
        return `
            <tr>
                <td><span class="time-value">${date}</span></td>
                <td>${h.title || 'Unknown'}</td>
                <td><span class="ticker-badge">${h.type || '--'}</span></td>
                <td><span class="status-badge ${statusClass}">${statusText}</span></td>
                <td>${h.actual_impact ? '📊 Measured' : '--'}</td>
            </tr>
        `;
    }).join('');
}

async function loadPromptStatus() {
    try {
        const response = await fetch('/api/coach/prompt');
        const status = await response.json();
        
        // Emphasized patterns
        const emphEl = document.getElementById('emphasizedPatterns');
        if (status.emphasized_patterns && status.emphasized_patterns.length > 0) {
            emphEl.innerHTML = status.emphasized_patterns.map(p => 
                `<span class="ticker-tag" style="background: rgba(0,255,136,0.15); color: var(--accent-green);">${p}</span>`
            ).join('');
        } else {
            emphEl.innerHTML = '<span style="color: var(--text-muted);">None yet</span>';
        }
        
        // Caution patterns
        const cautEl = document.getElementById('cautionPatterns');
        if (status.caution_patterns && status.caution_patterns.length > 0) {
            cautEl.innerHTML = status.caution_patterns.map(p => 
                `<span class="ticker-tag" style="background: rgba(255,68,102,0.15); color: var(--accent-red);">${p}</span>`
            ).join('');
        } else {
            cautEl.innerHTML = '<span style="color: var(--text-muted);">None yet</span>';
        }
        
        // Time filters
        const timeEl = document.getElementById('timeFilters');
        const avoid = status.avoid_hours || [];
        const prefer = status.prefer_hours || [];
        if (avoid.length > 0 || prefer.length > 0) {
            let html = '';
            if (avoid.length > 0) {
                html += `<span style="color: var(--accent-red);">Avoid: ${avoid.map(h => h + ':00').join(', ')}</span>`;
            }
            if (prefer.length > 0) {
                html += `<span style="color: var(--accent-green); margin-left: 16px;">Prefer: ${prefer.map(h => h + ':00').join(', ')}</span>`;
            }
            timeEl.innerHTML = html;
        } else {
            timeEl.innerHTML = '<span style="color: var(--text-muted);">None configured</span>';
        }
        
    } catch (error) {
        console.error('Failed to load prompt status:', error);
    }
}

function togglePromptStatus() {
    const content = document.getElementById('promptContent');
    const toggle = document.getElementById('promptToggle');
    content.classList.toggle('hidden');
    toggle.classList.toggle('collapsed');
}

async function resetPromptMods() {
    if (!confirm('Reset all AI prompt modifications? This will revert to the base prompt.')) return;
    
    try {
        await fetch('/api/coach/prompt/reset', { method: 'POST' });
        addLog('Prompt modifications reset', 'warning');
        loadPromptStatus();
    } catch (error) {
        addLog('Failed to reset prompt', 'error');
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    updateTime();
    setInterval(updateTime, 1000);
    
    // Setup ticker input listener
    const tickerInput = document.getElementById('tickersInput');
    if (tickerInput) {
        tickerInput.addEventListener('keydown', addTicker);
    }
    
    loadSettings();
    setWebhookUrl();
    fetchStatus();
    fetchPerformance();
    fetchTradeJournal();
    loadApexStatus();
    fetchCandleStatus();
    loadMarketRegime();
    
    setInterval(fetchStatus, 2000);
    setInterval(fetchPerformance, 5000);
    setInterval(fetchTradeJournal, 3000);
    setInterval(loadApexStatus, 10000);
    setInterval(fetchCandleStatus, 5000);
    setInterval(loadMarketRegime, 30000);  // Update market regime every 30s
    
    addLog('Dashboard v2 initialized', 'success');
    addLog('Apex rules tracking enabled', 'info');
    addLog('Market regime detection active', 'info');
});

