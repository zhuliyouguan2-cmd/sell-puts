import streamlit as st
import pandas as pd
import datetime
import pytz

# Import the core logic from your other file
from options_screener_logic import run_screener, TRADING_UNIVERSE

# --- Streamlit Page Configuration ---
st.set_page_config(
    page_title="Quantitative Put Selling Dashboard",
    page_icon="🏆",
    layout="wide",
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
st.title("🏆 Quantitative Put Selling Dashboard")
st.markdown("This dashboard screens for high-probability bull put spreads and ranks the best opportunities.")

# --- Load Data and Display Timestamp ---
all_results, last_run_timestamp = get_cached_screener_results()

col1, col2 = st.columns([4, 1])
with col1:
    st.info(f"**Showing cached results from the last run at: `{last_run_timestamp}`**. Data automatically refreshes every 1.5 hours.")
with col2:
    if st.button("🔄 Refresh Data Now"):
        st.cache_data.clear()
        st.rerun()

# --- Process Data ---
if not all_results:
    st.error("The screener did not return any data. This might be a temporary API issue.")
    st.stop()

all_results_df = pd.DataFrame(all_results)
passing_df = all_results_df[all_results_df['status'] == 'PASS'].copy()
if not passing_df.empty:
    # Ensure 'return_on_risk' is numeric before sorting
    passing_df['return_on_risk'] = pd.to_numeric(passing_df['return_on_risk'])


# --- Display Top 5 Opportunities ---
st.header("🥇 Top 5 Opportunities")
st.markdown("These are the highest-ranked trades based on **Return on Risk** that passed all filters.")

if not passing_df.empty:
    top_5_df = passing_df.sort_values(by='return_on_risk', ascending=False).head(5)
    
    # Format the DataFrame for better readability
    formatted_df = top_5_df.copy()
    formatted_df['current_price'] = formatted_df['current_price'].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "N/A")
    formatted_df['net_credit'] = formatted_df['net_credit'].apply(lambda x: f"${x:,.2f}")
    formatted_df['max_risk'] = formatted_df['max_risk'].apply(lambda x: f"${x:,.2f}")
    formatted_df['return_on_risk'] = formatted_df['return_on_risk'].apply(lambda x: f"{x:.2f}%")
    
    column_order = [
        'symbol', 'vol_rank', 'tech_score', 'current_price', 'return_on_risk', 'net_credit', 
        'max_risk', 'short_put_strike', 'long_put_strike'
    ]
    
    st.dataframe(
        formatted_df[column_order], 
        use_container_width=True,
        hide_index=True,
        column_config={
            "symbol": st.column_config.TextColumn("Ticker"),
            "vol_rank": st.column_config.TextColumn("Vol Rank", help="Proxy for IV Rank. Higher is better."),
            "tech_score": st.column_config.TextColumn("Tech Score"),
            "current_price": st.column_config.TextColumn("Underlying Price"),
            "return_on_risk": st.column_config.TextColumn("Return %"),
            "net_credit": st.column_config.TextColumn("Credit"),
            "max_risk": st.column_config.TextColumn("Max Risk"),
            "short_put_strike": st.column_config.NumberColumn("Short Strike"),
            "long_put_strike": st.column_config.NumberColumn("Long Strike"),
        }
    )
else:
    st.info("No trades passed all screening criteria in the last run.")


# --- Display All Scanned Results ---
st.header("🔍 All Scanned Underlyings")
st.markdown("Full results from the last scan. Rows highlighted in green passed all filters.")

# Function to highlight rows that passed
def highlight_pass(row):
    return ['background-color: #2E4E36'] * len(row) if row.status == 'PASS' else [''] * len(row)

# Prepare a simplified DataFrame for display
display_cols = ['symbol', 'vol_rank', 'status', 'reason']
display_df = all_results_df[display_cols].copy()
display_df.rename(columns={'symbol': 'Ticker', 'vol_rank': 'Vol Rank', 'status': 'Status', 'reason': 'Details'}, inplace=True)

st.dataframe(
    display_df.style.apply(highlight_pass, axis=1),
    use_container_width=True,
    hide_index=True,
)

with st.expander("📖 View Strategy Methodology"):
    st.markdown("""
    - **Volatility Rank > 40%:** Ensures we only sell options when the premium is relatively "rich".
    - **DTE:** Looks for options between **30-50 days** to expiration.
    - **Delta Selection:** Short strike delta between **-0.20 & -0.30**; Long strike delta around **-0.10**.
    - **Premium Rule:** Net credit must be at least **1/3 of the spread's width**.
    - **Technical Score:** Simple 2-point score (Price > 50-SMA, RSI < 70).
    """)
