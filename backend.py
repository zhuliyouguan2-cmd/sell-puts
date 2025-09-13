import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import norm
from datetime import datetime
import streamlit as st # Still need for caching decorator

# --- Caching ---
# The cache is managed here in the backend where the data fetching occurs.
@st.cache_data(ttl=900)
def get_stock_data(ticker):
    """
    Fetches serializable stock data from yfinance.
    Returns price, sector, and expiration dates, which are all serializable.
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        price = stock.history(period="1d")['Close'].iloc[-1]
        sector = info.get('sector', 'N/A')
        expirations = stock.options
        return price, sector, expirations
    except Exception as e:
        print(f"Error fetching stock data for {ticker}: {e}") # Log error
        return None, None, None

@st.cache_data(ttl=900)
def get_options_chain_puts(ticker, expiration):
    """
    Fetches the put options DataFrame for a specific ticker and expiration date.
    A pandas DataFrame is a serializable object.
    """
    try:
        stock = yf.Ticker(ticker)
        options = stock.option_chain(expiration)
        return options.puts # Return only the DataFrame
    except Exception:
        return None

# --- Calculation Logic ---
def black_scholes_put_delta(S, K, T, r, sigma):
    """
    Calculates the Black-Scholes delta for a European put option.
    """
    if T <= 0 or sigma <= 0:
        return 0.0 if S > K else -1.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    delta = norm.cdf(d1) - 1
    return delta

# --- Scoring Logic ---
def score_option(option, current_price, portfolio_value, max_sector_exposure_pct, sector):
    """Scores a single put option based on the defined strategy."""
    strike = option['strike']
    premium = option['lastPrice']
    iv = option['impliedVolatility']
    dte = (datetime.strptime(option['expirationDate'], '%Y-%m-%d') - datetime.now()).days
    
    if dte <= 0 or premium <= 0 or strike <= 0:
        return None

    # 1. Option-Specific Metrics
    capital_at_risk_per_share = strike - premium
    annualized_return = (premium / capital_at_risk_per_share) * (365 / dte) if capital_at_risk_per_share > 0 else 0
    
    if annualized_return > 0.20: score_ar = 5
    elif annualized_return >= 0.15: score_ar = 3
    elif annualized_return >= 0.10: score_ar = 1
    else: score_ar = 0

    if iv > 0.50: score_iv = 5
    elif iv >= 0.30: score_iv = 3
    elif iv >= 0.15: score_iv = 1
    else: score_iv = 0
    
    score_return_on_capital = (score_ar + score_iv) / 2
    
    T = dte / 365.0
    r = 0.04 
    delta = black_scholes_put_delta(current_price, strike, T, r, iv)
    abs_delta = abs(delta)

    if abs_delta < 0.25: score_delta = 5
    elif abs_delta <= 0.35: score_delta = 3
    elif abs_delta <= 0.45: score_delta = 1
    else: score_delta = 0

    margin_of_safety = (current_price - strike) / current_price
    if margin_of_safety > 0.15: score_mos = 5
    elif margin_of_safety >= 0.10: score_mos = 3
    elif margin_of_safety >= 0.05: score_mos = 1
    else: score_mos = 0

    score_prob_safety = (score_delta + score_mos) / 2

    # 2. Risk Management
    capital_at_risk_total = (strike * 100) - (premium * 100)
    risk_as_pct_portfolio = (capital_at_risk_total / portfolio_value) * 100 if portfolio_value > 0 else float('inf')

    if risk_as_pct_portfolio < 2: score_sizing = 5
    elif risk_as_pct_portfolio <= 3: score_sizing = 3
    elif risk_as_pct_portfolio <= 4: score_sizing = 1
    else: score_sizing = 0

    if max_sector_exposure_pct > 25: score_conc = 5
    elif max_sector_exposure_pct > 20: score_conc = 3
    elif max_sector_exposure_pct > 15: score_conc = 1
    else: score_conc = 0

    final_score = ((score_return_on_capital * 0.30) + \
                   (score_prob_safety * 0.30) + \
                   (score_sizing * 0.20) + \
                   (score_conc * 0.20)) / 5 * 100
    
    return {
        'Expiration': option['expirationDate'], 'Strike': strike, 'Premium': premium,
        'DTE': dte, 'IV': iv, 'Delta': delta, 'Ann. Return': annualized_return,
        'Margin of Safety': margin_of_safety, 'Score': final_score,
        'Ticker': option['ticker'], 'Sector': sector
    }

# --- Main Processing Function ---
def process_tickers(tickers, min_dte, max_dte, num_strikes_otm, portfolio_value, max_sector_exposure_pct, status_callback=None):
    """
    Main function to fetch, process, and score options for a list of tickers.
    """
    all_options = []
    
    for i, ticker in enumerate(tickers):
        if status_callback:
            status_callback(f"Fetching data for {ticker}...", (i + 1) / len(tickers))

        current_price, sector, expirations = get_stock_data(ticker)

        if current_price is None or not expirations:
            print(f"Skipping {ticker} due to missing data.")
            continue

        valid_expirations = []
        for exp_str in expirations:
            dte = (datetime.strptime(exp_str, '%Y-%m-%d') - datetime.now()).days
            if min_dte <= dte <= max_dte:
                valid_expirations.append(exp_str)

        for exp in valid_expirations:
            puts = get_options_chain_puts(ticker, exp)
            
            if puts is None or puts.empty: continue

            puts['ticker'] = ticker
            puts['expirationDate'] = exp

            otm_puts = puts[puts['strike'] < current_price].head(num_strikes_otm)

            for _, row in otm_puts.iterrows():
                score_data = score_option(row, current_price, portfolio_value, max_sector_exposure_pct, sector)
                if score_data:
                    all_options.append(score_data)
    
    if not all_options:
        return pd.DataFrame()

    return pd.DataFrame(all_options).sort_values(by='Score', ascending=False).reset_index(drop=True)
