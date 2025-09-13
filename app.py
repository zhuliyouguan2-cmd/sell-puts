import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# --- Configuration ---
st.set_page_config(
    page_title="Sell Puts Options Screener",
    page_icon="💸",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Caching Functions ---
@st.cache_data(ttl=3600) # Cache data for 1 hour
def get_top_tickers():
    """Fetches top 20 market cap tickers from a predefined list and adds ETFs."""
    # This is a static list to avoid relying on external APIs for this core functionality.
    # It should be updated periodically. As of late 2023.
    tickers = [
        'AAPL', 'MSFT', 'GOOG', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA',
        'BRK-B', 'LLY', 'V', 'JPM', 'WMT', 'XOM', 'UNH', 'MA',
        'JNJ', 'PG', 'HD', 'COST', 'SPY', 'QQQ'
    ]
    return tickers

@st.cache_data(ttl=3600)
def get_stock_data(ticker):
    """Fetches fundamental and price data for a given ticker."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="1y")

        # --- Data Extraction ---
        current_price = info.get('currentPrice', hist['Close'].iloc[-1])
        forward_pe = info.get('forwardPE')
        market_cap = info.get('marketCap', 0)
        ema_200 = hist['Close'].ewm(span=200, adjust=False).mean().iloc[-1]

        # --- Options Data ---
        # Get options expiration dates
        expirations = stock.options

        return {
            "ticker": ticker,
            "info": info,
            "current_price": current_price,
            "forward_pe": forward_pe,
            "market_cap": market_cap,
            "ema_200": ema_200,
            "expirations": expirations,
            "stock_object": stock
        }
    except Exception as e:
        st.error(f"Could not fetch data for {ticker}: {e}")
        return None


# --- Scoring Logic ---
def calculate_score(option_row):
    """
    Calculates a score for a put option based on risk and reward.
    The scoring strategy is as follows:
    1.  **Profitability Score (Return on Capital)**: Higher premium for a given strike price is better. Max 40 points.
    2.  **Safety Score (Distance from Strike)**: Further OTM (Out of the Money) is safer. Max 40 points.
    3.  **Valuation Score (Fundamental Health)**: Lower P/E and price below EMA200 is better. Max 20 points.
    """
    # --- Profitability Score (Max 40) ---
    # Return on Capital (ROC) = Premium / Strike Price. We cap it at 8% for scoring.
    roc = (option_row['lastPrice'] / option_row['strike']) * 100
    profit_score = min(roc / 8.0, 1.0) * 40

    # --- Safety Score (Max 40) ---
    # % Distance from current price. We cap it at 20% for scoring.
    distance_pct = ((option_row['current_price'] - option_row['strike']) / option_row['current_price']) * 100
    safety_score = min(distance_pct / 20.0, 1.0) * 40

    # --- Valuation Score (Max 20) ---
    valuation_score = 0
    # Forward P/E component (Max 10 points) - Lower is better. Capped at 35.
    if option_row['forward_pe'] and option_row['forward_pe'] > 0:
        # Inverse relationship: higher PE is worse.
        pe_score = max(0, 1 - (option_row['forward_pe'] / 35.0)) * 10
        valuation_score += pe_score

    # EMA 200 component (Max 10 points) - Is the stock in an uptrend?
    if option_row['current_price'] > option_row['ema_200']:
        valuation_score += 5
    # Is it significantly below its long-term average (potential discount)?
    if option_row['current_price'] < option_row['ema_200'] * 1.1: # Within 10%
         valuation_score += 5


    return profit_score + safety_score + valuation_score

# --- Main App ---
st.title("📈 High-Quality Sell Puts Screener")
st.write("""
This tool scans the top 20 US stocks and major ETFs (SPY, QQQ) to find potentially attractive put options to sell.
The **Recommendation Score** balances profit, risk, and company valuation to highlight opportunities.
A higher score suggests a better balance of risk and reward.
""")

# --- Sidebar Inputs ---
st.sidebar.header("Filter Options")
days_to_expiry_min = st.sidebar.slider("Minimum Days to Expiry", 0, 90, 21)
days_to_expiry_max = st.sidebar.slider("Maximum Days to Expiry", 0, 90, 45)
min_distance_from_money = st.sidebar.slider("Minimum OTM % (Out of the Money)", 1.0, 30.0, 5.0, 0.5)
min_roc = st.sidebar.slider("Minimum Return on Capital (%)", 0.5, 10.0, 1.0, 0.1)
min_volume = st.sidebar.slider("Minimum Option Volume", 0, 500, 10)
min_score = st.sidebar.slider("Minimum Recommendation Score", 0, 100, 50)


# --- Data Fetching and Processing ---
tickers = get_top_tickers()
all_options = []
progress_bar = st.progress(0)
status_text = st.empty()

for i, ticker in enumerate(tickers):
    status_text.text(f"Fetching data for {ticker}...")
    stock_data = get_stock_data(ticker)
    if not stock_data:
        continue

    # Filter expirations based on user input
    today = datetime.now()
    min_exp_date = today + timedelta(days=days_to_expiry_min)
    max_exp_date = today + timedelta(days=days_to_expiry_max)

    valid_expirations = [
        exp for exp in stock_data['expirations']
        if min_exp_date <= datetime.strptime(exp, '%Y-%m-%d') <= max_exp_date
    ]

    for exp in valid_expirations:
        try:
            # Puts options chain
            opt_chain = stock_data['stock_object'].option_chain(exp)
            puts = opt_chain.puts

            # Add stock-level data to the options dataframe
            puts['ticker'] = ticker
            puts['current_price'] = stock_data['current_price']
            puts['forward_pe'] = stock_data['forward_pe']
            puts['ema_200'] = stock_data['ema_200']
            puts['expiry'] = exp
            all_options.append(puts)
        except Exception as e:
            # Sometimes an expiration date might not have data
            pass
    progress_bar.progress((i + 1) / len(tickers))

status_text.text("Processing complete!")

if not all_options:
    st.warning("No options data found for the selected criteria. Try expanding your filters.")
else:
    # --- DataFrame Assembly and Filtering ---
    df = pd.concat(all_options, ignore_index=True)

    # 1. Basic Filters
    df_filtered = df[
        (df['volume'] >= min_volume) &
        (df['openInterest'] >= 1) &
        (df['lastPrice'] > 0.1) # Filter out very cheap options
    ].copy()

    # 2. OTM Filter
    df_filtered['distance_pct'] = ((df_filtered['current_price'] - df_filtered['strike']) / df_filtered['current_price']) * 100
    df_filtered = df_filtered[df_filtered['distance_pct'] >= min_distance_from_money]

    # 3. Return on Capital (ROC) Filter
    df_filtered['roc_pct'] = (df_filtered['lastPrice'] / df_filtered['strike']) * 100
    df_filtered = df_filtered[df_filtered['roc_pct'] >= min_roc]

    # 4. Days to Expiry
    df_filtered['dte'] = (pd.to_datetime(df_filtered['expiry']) - datetime.now()).dt.days


    # --- Scoring ---
    if not df_filtered.empty:
        df_filtered['score'] = df_filtered.apply(calculate_score, axis=1)
        df_scored = df_filtered[df_filtered['score'] >= min_score]

        # --- Display Results ---
        st.subheader("Recommended Put Options to Sell")

        if not df_scored.empty:
            # Final formatting for display
            display_df = df_scored.sort_values(by='score', ascending=False).head(50) # Show top 50
            display_df = display_df[[
                'ticker', 'strike', 'expiry', 'dte', 'lastPrice', 'roc_pct',
                'distance_pct', 'volume', 'score', 'current_price'
            ]].rename(columns={
                'ticker': 'Ticker', 'strike': 'Strike', 'expiry': 'Expiry', 'dte': 'DTE',
                'lastPrice': 'Premium', 'roc_pct': 'Return %', 'distance_pct': 'OTM %',
                'volume': 'Volume', 'score': 'Score', 'current_price': 'Stock Price'
            })

            # Format numbers for better readability
            display_df['Premium'] = display_df['Premium'].map('${:,.2f}'.format)
            display_df['Return %'] = display_df['Return %'].map('{:,.2f}%'.format)
            display_df['OTM %'] = display_df['OTM %'].map('{:,.2f}%'.format)
            display_df['Score'] = display_df['Score'].map('{:.1f}'.format)
            display_df['Stock Price'] = display_df['Stock Price'].map('${:,.2f}'.format)

            st.dataframe(display_df, use_container_width=True, hide_index=True)
        else:
            st.info("No options met the minimum score. Try adjusting the filters in the sidebar.")
    else:
        st.info("No options met the initial criteria. Try adjusting the filters in the sidebar.")

st.sidebar.markdown("---")
st.sidebar.info("Disclaimer: This is a financial tool for informational purposes only. Trading options involves significant risk. Do your own research.")
