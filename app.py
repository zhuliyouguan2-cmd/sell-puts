import streamlit as st
import pandas as pd
import datetime
import pytz

# Import the core logic from your other file
from options_screener_logic import run_screener, TRADING_UNIVERSE

# --- Streamlit Page Configuration ---
st.set_page_config(
    page_title="Quantitative Put Selling Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- Caching ---
# Cache the data to avoid re-running the heavy yfinance calls on every interaction.
# TTL (Time-To-Live) is set to 5400 seconds (1.5 hours) to match the desired refresh rate.
@st.cache_data(ttl=5400)
def get_cached_screener_results():
    """
    Runs the main screener function and returns the results along with a timestamp.
    The @st.cache_data decorator handles the caching.
    """
    print(f"CACHE MISS: Running the full screener logic at {datetime.datetime.now()}.")
    results = run_screener(TRADING_UNIVERSE)
    timestamp = datetime.datetime.now(pytz.timezone("US/Central")).strftime('%Y-%m-%d %H:%M:%S %Z')
    return results, timestamp

# --- Dashboard UI ---
st.title("📈 Quantitative Put Selling Dashboard")
st.markdown("This dashboard screens for high-probability bull put spreads based on a quantitative scoring model.")

# --- Load Data and Display Timestamp ---
results, last_run_timestamp = get_cached_screener_results()

col1, col2 = st.columns([4, 1])
with col1:
    st.info(f"**Showing cached results from the last run at: `{last_run_timestamp}`**. Data automatically refreshes every 1.5 hours.")
with col2:
    if st.button("🔄 Refresh Data Now"):
        st.cache_data.clear()
        st.rerun()

# --- Display Key Metrics ---
if results:
    results_df = pd.DataFrame(results)
    st.metric(label="High-Quality Opportunities Found", value=len(results_df))
else:
    results_df = pd.DataFrame() # Ensure df exists even if empty
    st.metric(label="High-Quality Opportunities Found", value=0)

st.header("Trade Opportunities")
st.markdown("The table below shows potential trades that have passed all quantitative filters. Review these options to select your trades.")

if not results_df.empty:
    # --- Format the DataFrame for better readability ---
    formatted_df = results_df.copy()

    # Apply formatting
    formatted_df['current_price'] = formatted_df['current_price'].apply(lambda x: f"${x:,.2f}")
    formatted_df['net_credit'] = formatted_df['net_credit'].apply(lambda x: f"${x:,.2f}")
    formatted_df['max_risk'] = formatted_df['max_risk'].apply(lambda x: f"${x:,.2f}")
    formatted_df['return_on_risk'] = formatted_df['return_on_risk'].apply(lambda x: f"{x:.2f}%")
    
    # Define column order and configuration
    column_order = [
        'symbol', 'vol_rank', 'tech_score', 'current_price', 'return_on_risk', 'net_credit', 
        'max_risk', 'short_put_strike', 'long_put_strike', 'short_put_delta', 
        'long_put_delta', 'spread_width'
    ]
    
    st.dataframe(
        formatted_df[column_order], 
        use_container_width=True,
        hide_index=True,
        column_config={
            "symbol": st.column_config.TextColumn("Ticker"),
            "vol_rank": st.column_config.TextColumn("Vol Rank", help="Historical Volatility Rank (Proxy for IV Rank). Higher is better."),
            "tech_score": st.column_config.TextColumn("Tech Score", help="Technical health score (max 2)."),
            "return_on_risk": st.column_config.TextColumn("Return %", help="The potential return on risk for the trade."),
            "net_credit": st.column_config.TextColumn("Credit"),
            "max_risk": st.column_config.TextColumn("Max Risk"),
            "short_put_strike": st.column_config.NumberColumn("Short Strike"),
            "long_put_strike": st.column_config.NumberColumn("Long Strike"),
            "short_put_delta": st.column_config.NumberColumn("Short Δ", format="%.3f"),
            "long_put_delta": st.column_config.NumberColumn("Long Δ", format="%.3f"),
            "spread_width": st.column_config.NumberColumn("Width")
        }
    )
else:
    st.warning("No trading opportunities were found that meet all the screening criteria in the last run.")


# --- Methodology Expander ---
with st.expander("📖 Click here to see the Strategy Methodology"):
    st.markdown("""
    This screener identifies potential bull put spread opportunities by applying a series of quantitative filters. A trade must pass all stages to be displayed.

    - **Stage 1: Universe Filter**
      - **Eligible Underlyings:** Only screens highly liquid, pre-approved stocks and ETFs (`SPY, QQQ, AAPL`, etc.).

    - **Stage 2: Macro Environment Filter**
      - **Volatility Rank > 40%:** Ensures we are only selling options when the premium is relatively "rich" compared to its 52-week history. This is the most important filter for getting paid for the risk.

    - **Stage 3: Trade Structure Filter**
      - **Days to Expiration (DTE):** Looks for options between **30-50 days** to expiration to capture the best part of the time decay curve.
      - **Short Strike Delta:** Selects a short put strike with a delta between **-0.20 and -0.30**.
      - **Long Strike Delta:** Selects a long put strike with a delta around **-0.10** to define risk.
      - **Premium Rule:** The net credit received must be at least **1/3 of the spread's width**.

    - **Stage 4: Technical Confluence Score**
      - A simple 2-point score to avoid selling into obviously weak stocks.
      - `+1 point` if Price > 50-day SMA.
      - `+1 point` if 14-day RSI < 70.
    """)
