#!/bin/bash

# ============================================
# 🎯 PROP FIRM SCANNER - ONE-CLICK LAUNCHER
# ============================================
# Now with auto-ngrok built into Python!

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

PROJECT_DIR="/Users/williamgrello/Desktop/Propfirm_scanner/prop_firm_scanner"

clear
echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  🎯 PROP FIRM SCANNER v2${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# Change to project directory
cd "$PROJECT_DIR"

# Kill any existing processes on our ports
echo -e "${YELLOW}Cleaning up old processes...${NC}"
lsof -ti:5055 | xargs kill -9 2>/dev/null
pkill -f ngrok 2>/dev/null
sleep 1

echo ""
echo -e "${GREEN}Starting scanner with auto-ngrok...${NC}"
echo -e "${BLUE}Dashboard will open automatically!${NC}"
echo ""
echo "============================================"
echo ""

# Run the scanner (ngrok and browser open automatically)
python3 scanners/tradingview_webhook_scanner.py
