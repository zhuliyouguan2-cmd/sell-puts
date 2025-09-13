import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import norm
from datetime import datetime
import streamlit as st

# --- Caching ---
@st.cache_data(ttl=900)
def get_stock_data_and_technicals(ticker):
    """
    Fetches serializable stock data and calculates technical indicators.
    Returns price, sector, expirations, RSI, and SMA details.
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="250d") # Fetch enough data for SMAs

        if hist.empty:
            return None, None, None, None, None, None

        price = hist['Close'].iloc[-1]
        sector = info.get('sector', 'N/A')
        expirations = stock.options

        # --- Calculate Technical Indicators ---
        # RSI (Relative Strength Index)
        delta = hist['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1] if pd.notna(rsi.iloc[-1]) else 50 # Default to neutral if NaN

        # SMAs (Simple Moving Averages)
        sma_50 = hist['Close'].rolling(window=50).mean().iloc[-1]
        sma_200 = hist['Close'].rolling(window=200).mean().iloc[-1]

        return price, sector, expirations, current_rsi, sma_50, sma_200
    except Exception as e:
        print(f"Error fetching technical data for {ticker}: {e}")
        return None, None, None, None, None, None


@st.cache_data(ttl=900)
def get_options_chain_puts(ticker, expiration):
    """Fetches the put options DataFrame for a specific ticker and expiration date."""
    try:
        stock = yf.Ticker(ticker)
        options = stock.option_chain(expiration)
        return options.puts
    except Exception:
        return None

# --- Calculation Logic ---
def black_scholes_put_delta(S, K, T, r, sigma):
    """Calculates the Black-Scholes delta for a European put option."""
    if T <= 0 or sigma <= 0:
        return 0.0 if S > K else -1.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    delta = norm.cdf(d1) - 1
    return delta

# --- Scoring Logic ---
def score_option(option, current_price, portfolio_value, sector, rsi, sma_50, sma_200):
    """Scores a single put option based on the defined strategy."""
    strike = option['strike']
    premium = option['lastPrice']
    iv = option['impliedVolatility']
    dte = (datetime.strptime(option['expirationDate'], '%Y-%m-%d') - datetime.now()).days
    
    if dte <= 0 or premium <= 0 or strike <= 0:
        return None

    # Filter out any options with less than 8% annualized return
    capital_at_risk_per_share = strike - premium
    annualized_return = (premium / capital_at_risk_per_share) * (365 / dte) if capital_at_risk_per_share > 0 else 0
    if annualized_return < 0.08:
        return None

    # 1. Return on Capital (35% Weight)
    if annualized_return > 0.20: score_ar = 5
    elif annualized_return >= 0.15: score_ar = 3
    elif annualized_return >= 0.10: score_ar = 1
    else: score_ar = 0
    if iv > 0.50: score_iv = 5
    elif iv >= 0.30: score_iv = 3
    elif iv >= 0.15: score_iv = 1
    else: score_iv = 0
    score_return_on_capital = (score_ar + score_iv) / 2

    # 2. Probability & Safety (35% Weight)
    T = dte / 365.0
    r = 0.04 
    delta = black_scholes_put_delta(current_price, strike, T, r, iv)
    abs_delta = abs(delta)
    if abs_delta < 0.15: score_delta = 5
    elif abs_delta <= 0.25: score_delta = 3
    elif abs_delta <= 0.35: score_delta = 1
    else: score_delta = 0
    margin_of_safety = (current_price - strike) / current_price
    if margin_of_safety > 0.15: score_mos = 5
    elif margin_of_safety >= 0.10: score_mos = 3
    elif margin_of_safety >= 0.05: score_mos = 1
    else: score_mos = 0
    score_prob_safety = (score_delta + score_mos) / 2

    # 3. Basic Technical Indicators (20% Weight)
    if rsi < 35: score_rsi = 5 # Oversold, good for reversal
    elif rsi < 45: score_rsi = 3
    elif rsi < 60: score_rsi = 1
    else: score_rsi = 0 # Overbought, risky
    
    if current_price > sma_200 * 1.03: score_sma = 5 # Strong uptrend
    elif current_price > sma_200: score_sma = 3 # Uptrend
    elif current_price > sma_50: score_sma = 1
    else: score_sma = 0 # Potential downtrend
    score_technicals = (score_rsi + score_sma) / 2

    # 4. Risk Management (10% Weight)
    capital_at_risk_total = (strike * 100) - (premium * 100)
    risk_as_pct_portfolio = (capital_at_risk_total / portfolio_value) * 100 if portfolio_value > 0 else float('inf')
    if risk_as_pct_portfolio < 4: score_sizing = 5
    elif risk_as_pct_portfolio <= 6: score_sizing = 3
    elif risk_as_pct_portfolio <= 8: score_sizing = 1
    else: score_sizing = 0

    # Final Score Calculation with new weights
    final_score = ((score_return_on_capital * 0.35) + \
                   (score_prob_safety * 0.35) + \
                   (score_technicals * 0.20) + \
                   (score_sizing * 0.10)) / 5 * 100
    
    return {
        'Expiration': option['expirationDate'], 'Strike': strike, 'Premium': premium,
        'DTE': dte, 'IV': iv, 'Delta': delta, 'Ann. Return': annualized_return,
        'Margin of Safety': margin_of_safety, 'Score': final_score,
        'Ticker': option['ticker'], 'Sector': sector
    }

# --- Main Processing Function ---
def process_tickers(tickers, min_dte, max_dte, num_strikes_otm, portfolio_value, status_callback=None):
    all_options = []
    for i, ticker in enumerate(tickers):
        if status_callback:
            status_callback(f"Fetching data for {ticker}...", (i + 1) / len(tickers))

        current_price, sector, expirations, rsi, sma_50, sma_200 = get_stock_data_and_technicals(ticker)

        if current_price is None or not expirations:
            print(f"Skipping {ticker} due to missing data.")
            continue

        valid_expirations = [exp for exp in expirations if min_dte <= (datetime.strptime(exp, '%Y-%m-%d') - datetime.now()).days <= max_dte]

        for exp in valid_expirations:
            puts = get_options_chain_puts(ticker, exp)
            if puts is None or puts.empty: continue
            puts['ticker'] = ticker
            puts['expirationDate'] = exp
            otm_puts = puts[puts['strike'] < current_price].head(num_strikes_otm)

            for _, row in otm_puts.iterrows():
                score_data = score_option(row, current_price, portfolio_value, sector, rsi, sma_50, sma_200)
                if score_data:
                    all_options.append(score_data)
    
    if not all_options:
        return pd.DataFrame()

    return pd.DataFrame(all_options).sort_values(by='Score', ascending=False).reset_index(drop=True)
