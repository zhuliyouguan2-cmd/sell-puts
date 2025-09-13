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
        delta_hist = hist['Close'].diff()
        gain = (delta_hist.where(delta_hist > 0, 0)).rolling(window=14).mean()
        loss = (-delta_hist.where(delta_hist < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1] if pd.notna(rsi.iloc[-1]) else 50

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

def linear_scale(value, worst, best):
    """Linearly scales a value from a 'worst' to 'best' range to a 0-5 score."""
    # If the best value is lower than the worst, reverse the logic (lower is better)
    if best < worst:
        worst, best = best, worst
        value = max(worst, min(best, value)) # Clamp
        score = 5 * (best - value) / (best - worst)
    else:
        value = max(worst, min(best, value)) # Clamp
        score = 5 * (value - worst) / (best - worst)
    return score

# --- Scoring Logic ---
def score_option(option, current_price, portfolio_value, sector, rsi, sma_50, sma_200):
    """Scores a single put option using continuous linear functions."""
    strike = option['strike']
    premium = option['lastPrice']
    iv = option['impliedVolatility']
    dte = (datetime.strptime(option['expirationDate'], '%Y-%m-%d') - datetime.now()).days
    
    if dte <= 0 or premium <= 0 or strike <= 0:
        return None

    capital_at_risk_per_share = strike - premium
    annualized_return = (premium / capital_at_risk_per_share) * (365 / dte) if capital_at_risk_per_share > 0 else 0
    if annualized_return < 0.08:
        return None

    # 1. Return on Capital (20% Weight)
    score_ar = linear_scale(annualized_return, worst=0.08, best=0.25)
    score_iv = linear_scale(iv, worst=0.15, best=0.60)
    score_return_on_capital = (score_ar + score_iv) / 2

    # 2. Probability & Safety (50% Weight)
    T = dte / 365.0
    r = 0.04 
    delta = black_scholes_put_delta(current_price, strike, T, r, iv)
    abs_delta = abs(delta)
    score_delta = linear_scale(abs_delta, worst=0.35, best=0.10) # Lower is better
    margin_of_safety = (current_price - strike) / current_price
    score_mos = linear_scale(margin_of_safety, worst=0.05, best=0.20)
    score_prob_safety = (score_delta + score_mos) / 2

    # 3. Basic Technical Indicators (20% Weight)
    score_rsi = linear_scale(rsi, worst=65, best=35) # Lower is better
    price_vs_sma_pct = (current_price - sma_200) / sma_200
    score_sma = linear_scale(price_vs_sma_pct, worst=0.0, best=0.15) # Higher % above SMA is better
    score_technicals = (score_rsi + score_sma) / 2

    # 4. Risk Management (10% Weight)
    capital_at_risk_total = (strike * 100) - (premium * 100)
    risk_as_pct_portfolio = (capital_at_risk_total / portfolio_value) * 100 if portfolio_value > 0 else float('inf')
    score_sizing = linear_scale(risk_as_pct_portfolio, worst=10.0, best=1.0) # Lower is better

    # Final Score Calculation
    final_score = ((score_return_on_capital * 0.20) + \
                   (score_prob_safety * 0.50) + \
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

    df = pd.DataFrame(all_options)
    
    # Define the desired column order with Ticker first
    column_order = [
        'Ticker', 'Expiration', 'Strike', 'Premium', 'Score', 'Ann. Return', 
        'Margin of Safety', 'DTE', 'IV', 'Delta', 'Sector'
    ]
    # Reorder the DataFrame, handling potential missing columns gracefully
    df = df.reindex(columns=column_order)

    return df.sort_values(by='Score', ascending=False).reset_index(drop=True)
