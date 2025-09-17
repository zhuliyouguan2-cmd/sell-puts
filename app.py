import streamlit as st
import pandas as pd
from backend import process_tickers # Import from backend

st.set_page_config(layout="wide")

# --- UI Styling ---
st.markdown("""
    <style>
    .stDataFrame {
        font-size: 1.1rem;
    }
    .stProgress > div > div > div > div {
        background-image: linear-gradient(to right, #4facfe 0%, #00f2fe 100%);
    }
    </style>
""", unsafe_allow_html=True)

st.title("📈 Value Investor's Put Option Screener")
st.markdown("Find attractive put-selling opportunities based on your pre-vetted list of stocks.")

# --- Scoring Logic Expander ---
with st.expander("How are these options scored?"):
    st.markdown("""
    The final score (out of 100) is a weighted average of four key areas:

    **1. Return on Capital (35% Weight)**
    - **Annualized Return:** The theoretical return if you held the position for a year.
    - **Implied Volatility (IV):** Rewards a healthy level of IV for higher premiums.

    **2. Probability & Safety (35% Weight)**
    - **Delta:** A lower delta (lower probability of expiring in-the-money) is safer and scores higher.
    - **Margin of Safety:** The percentage the stock price is *above* the strike price. A larger buffer is safer.

    **3. Basic Technicals (20% Weight)**
    - **Relative Strength Index (RSI):** Favors stocks that are not in "overbought" territory.
    - **Simple Moving Average (SMA):** Rewards stocks trading above their 50-day and 200-day moving averages, indicating a healthy uptrend.

    **4. Risk Management (10% Weight)**
    - **Position Sizing:** Calculates the capital at risk as a percentage of your portfolio. Smaller positions are safer.
    
    _Note: Any option with less than an 8% annualized return is automatically filtered out._
    """)

# --- Sidebar Inputs ---
st.sidebar.header("Your Portfolio & Strategy")

# List of tickers
tickers_input = st.sidebar.text_area(
    "Enter Tickers (comma-separated)", 
    "NVDA, UNH, GOOG, AAPL, BRKB, TSM, QQQ, SPY"
)

# Portfolio value
portfolio_value = st.sidebar.number_input(
    "Total Portfolio Value ($)", 
    min_value=50000, 
    max_value=1000000, 
    value=200000, 
    step=10000,
    help="Used to calculate position sizing score."
)

st.sidebar.header("Options Filtering")
# DTE range
min_dte, max_dte = st.sidebar.slider(
    "Days to Expiration (DTE) Range", 
    1, 90, (20, 45),
    help="What range of expiration dates are you interested in?"
)


# --- Main Application Logic ---
if st.sidebar.button("Find Opportunities", type="primary"):
    # Clean up ticker list
    tickers_list = [ticker.strip().upper() for ticker in tickers_input.split(',') if ticker.strip()]
    
    if not tickers_list:
        st.warning("Please enter at least one ticker.")
    else:
        # Progress bar
        progress_bar = st.progress(0)
        status_text = st.empty()

        def update_progress(message, percent_complete):
            status_text.text(message)
            progress_bar.progress(percent_complete)

        with st.spinner("Analyzing options chains... This may take a moment."):
            results = process_tickers(
                tickers_list,
                min_dte,
                max_dte,
                portfolio_value,
                status_callback=update_progress
            )
        
        status_text.text("Analysis complete!")
        progress_bar.empty()

        if results.empty:
            st.info("No options found matching your criteria. Try expanding the DTE range or adding more tickers.")
        else:
            # --- REVISION ---
            # Group by ticker and select the top 5 results for each.
            # This assumes the 'results' DataFrame is already sorted by score from the backend.
            display_data = results.groupby('Ticker').head(5)
            
            # st.success(f"Found {len(display_data)} potential opportunities, showing the top 5 per ticker.")
            
            # Format and display the dataframe
            results_display = display_data.copy()
            results_display['Premium'] = results_display['Premium'].map('${:,.2f}'.format)
            results_display['Strike'] = results_display['Strike'].map('{:,.2f}'.format)
            results_display['Score'] = results_display['Score'].map('{:.1f}'.format)
            results_display['IV Rank'] = results_display['IV Rank'].map('{:.1%}'.format)
            results_display['Delta'] = results_display['Delta'].map('{:.3f}'.format)
            results_display['Ann. Return'] = results_display['Ann. Return'].map('{:.1%}'.format)
            results_display['Margin of Safety'] = results_display['Margin of Safety'].map('{:.1%}'.format)
            
            st.dataframe(results_display, use_container_width=True)
else:
    st.info("Enter your parameters in the sidebar and click 'Find Opportunities' to begin.")
