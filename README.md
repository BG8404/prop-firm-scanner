# 🎯 Prop Firm Scanner v2

AI-powered futures trading scanner with TradingView webhook integration, Apex rules tracking, and performance analytics.

## 🆕 New in v2

### ⚠️ Apex Trader Funding Rules
- **Daily Loss Limit** - Warnings at 80%, auto-block at 100%
- **Trailing Drawdown** - Real-time tracking from high water mark
- **Consistency Rule** - No single day > 30% of total profits
- Configure via Dashboard → Apex Rules tab

### 📈 Performance Analytics
- Win rate chart over time
- P&L cumulative chart  
- Best/worst tickers analysis
- Performance by confidence level
- Long vs Short comparison
- Win/loss streak tracking

### 🤖 AI Self-Tuning
- Analyzes your trading history
- Finds optimal confidence threshold
- Recommends settings improvements
- One-click apply recommendations

### 🧠 AI Strategy Coach (Phase 5 - NEW)
- **Prompt Evolution** - Learns which analysis patterns win, suggests prompt changes
- **Smart Filters** - Tests confidence/R:R combinations, recommends optimal settings  
- **Pattern Recognition** - Identifies winning setup types and entry styles
- **Time Optimization** - Finds best/worst trading hours and days
- **Market Regime Detection** - Detects trending/ranging/choppy conditions
- Suggestions with clear explanations - you review and approve before applying
- Tracks suggestion outcomes to measure actual vs projected impact

### 📊 Dashboard at localhost:5055
| Tab | Features |
|-----|----------|
| Dashboard | Quick stats, trade journal, signals, live feed |
| Apex Rules | Progress bars, account config, warnings |
| Analytics | Charts, ticker analysis, confidence breakdown |
| AI Coach | Suggestions with explanations, approve/reject, prompt status |

---

## 📁 Project Structure

```
prop_firm_scanner/
├── scanners/
│   ├── tradingview_webhook_scanner.py   # Port 5055 - TradingView webhook receiver
│   └── futures_scanner.py               # Port 5060 - Polling-based scanner (yfinance)
├── database.py              # SQLite trade journal
├── outcome_tracker.py       # Auto win/loss detection
├── apex_rules.py            # Apex Trader Funding rules
├── analytics.py             # Performance analytics
├── ai_tuning.py             # AI self-tuning engine
├── strategy_coach.py        # AI Strategy Coach (NEW)
├── suggestion_manager.py    # Suggestion tracking (NEW)
├── prompt_evolver.py        # Dynamic prompt building (NEW)
├── market_regime.py         # Market condition detection (NEW)
├── settings.json            # Scanner settings
├── templates/
│   └── dashboard.html       # Dashboard UI
├── static/
│   ├── dashboard.css        # Dashboard styles (NEW)
│   └── dashboard.js         # Dashboard logic (NEW)
├── trade_journal.db         # SQLite database
├── requirements.txt
└── README.md
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
cd prop_firm_scanner
pip install -r requirements.txt
```

Or install individually:

```bash
pip install flask openai requests pyngrok pandas yfinance
```

### 2. Configure API Keys

⚠️ **Important**: Both scanner files contain hardcoded API keys and email credentials. For production use, move these to environment variables:

```bash
export OPENAI_API_KEY="your-key-here"
export EMAIL_PASS="your-app-password"
```

---

## 📡 Scanner 1: TradingView Webhook Scanner

**Port: 5055**

This scanner receives real-time candle data from TradingView alerts via webhook.

### Run the Scanner

```bash
cd prop_firm_scanner
python3 scanners/tradingview_webhook_scanner.py
```

### Set Up ngrok Tunnel

In a **separate terminal**:

```bash
ngrok http 5055
```

Copy the HTTPS URL (e.g., `https://abc123.ngrok.io`)

### Configure TradingView Alerts

1. Open TradingView
2. Create a new Alert on your chart
3. Set **Webhook URL** to: `https://your-ngrok-url.ngrok.io/webhook`
4. Set **Alert Message** (JSON format):

```json
{
    "ticker": "{{ticker}}",
    "timeframe": "1m",
    "time": "{{time}}",
    "open": {{open}},
    "high": {{high}},
    "low": {{low}},
    "close": {{close}},
    "volume": {{volume}}
}
```

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check - shows status and candle counts |
| `/webhook` | POST | Main webhook endpoint for TradingView |
| `/test` | POST | Manual trigger for AI analysis |

### Test the Webhook

```bash
curl -X POST http://localhost:5055/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "ticker": "MNQ",
    "timeframe": "1m",
    "time": "2025-12-01 12:30:00",
    "open": 21450.25,
    "high": 21452.50,
    "low": 21448.00,
    "close": 21451.75,
    "volume": 1523
  }'
```

---

## 📊 Scanner 2: Futures Scanner (Polling)

**Port: 5060**

This scanner polls Yahoo Finance for real-time futures data and runs AI analysis every minute.

### Run the Scanner

```bash
cd prop_firm_scanner
python3 scanners/futures_scanner.py
```

### Default Tickers

- MNQ=F (Micro Nasdaq)
- MES=F (Micro S&P 500)
- MGC=F (Micro Gold)

### Health Check Endpoint

```bash
curl http://localhost:5060
```

Returns scanner status, last scan time, and alerts sent.

---

## ⚙️ Configuration Options

Both scanners share these quality filter settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `MIN_CONFIDENCE` | 70% | Minimum AI confidence to trigger alert |
| `MAX_PRICE_DRIFT_TICKS` | 15 | Max ticks between current price and entry |
| `MIN_RISK_REWARD` | 2.0 | Minimum R:R ratio |
| `REQUIRE_MOMENTUM_ALIGNMENT` | True | Check if recent candles align with direction |

---

## 📧 Email Alerts

Both scanners can send email alerts via Gmail SMTP. Configure these settings:

```python
ENABLE_EMAIL_ALERTS = True
EMAIL_FROM = "your-email@gmail.com"
EMAIL_TO = "recipient@email.com"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_USER = "your-email@gmail.com"
EMAIL_PASS = "your-app-password"  # Use Gmail App Password
```

### Get Gmail App Password

1. Go to Google Account → Security
2. Enable 2-Step Verification
3. Create an App Password for "Mail"
4. Use that 16-character password

---

## 🖥️ Running in Cursor IDE

### Option 1: Run in Terminal Panel

1. Open Terminal in Cursor (`Ctrl+`` ` or `Cmd+`` `)
2. Navigate to project:
   ```bash
   cd /Users/williamgrello/Desktop/Propfirm_scanner/prop_firm_scanner
   ```
3. Run either scanner:
   ```bash
   python3 scanners/tradingview_webhook_scanner.py
   # OR
   python3 scanners/futures_scanner.py
   ```

### Option 2: Run Both Scanners

Open **two terminal tabs** in Cursor:

**Terminal 1:**
```bash
cd /Users/williamgrello/Desktop/Propfirm_scanner/prop_firm_scanner
python3 scanners/tradingview_webhook_scanner.py
```

**Terminal 2:**
```bash
cd /Users/williamgrello/Desktop/Propfirm_scanner/prop_firm_scanner
python3 scanners/futures_scanner.py
```

### Option 3: Using ngrok with Cursor

**Terminal 3 (for ngrok):**
```bash
ngrok http 5055
```

---

## 🔧 Troubleshooting

### Port Already in Use

```bash
# Find process using port 5055
lsof -i :5055

# Kill the process
kill -9 <PID>
```

### ngrok Connection Issues

1. Sign up for free ngrok account: https://ngrok.com
2. Authenticate ngrok:
   ```bash
   ngrok config add-authtoken YOUR_TOKEN
   ```

### No Data from yfinance

- Yahoo Finance may have rate limits
- Check market hours (futures trade nearly 24/7 Sun-Fri)
- Try different tickers

### OpenAI API Errors

- Verify API key is valid
- Check API usage limits
- Ensure sufficient credits

### Email Not Sending

- Use Gmail App Password (not regular password)
- Enable "Less secure app access" if needed
- Check spam folder

---

## 📝 Supported Tickers

| Ticker | Name | Tick Size | Typical SL |
|--------|------|-----------|------------|
| MNQ=F | Micro Nasdaq | 0.25 | 12-30 ticks |
| MES=F | Micro S&P 500 | 0.25 | 10-20 ticks |
| MGC=F | Micro Gold | 0.10 | 15-40 ticks |
| MCL=F | Micro Crude | 0.01 | 30-70 ticks |
| M2K=F | Micro Russell | 0.10 | 20-50 ticks |

---

## 🔒 Security Notes

⚠️ **Before deploying to production:**

1. Move API keys to environment variables
2. Move email credentials to environment variables
3. Use `.env` file with `python-dotenv`
4. Add `.env` to `.gitignore`

Example `.env` file:
```
OPENAI_API_KEY=sk-proj-xxx
EMAIL_PASS=xxxx xxxx xxxx xxxx
```

---

## 📜 License

MIT License - Use at your own risk. This is not financial advice.

