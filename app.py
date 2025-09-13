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
    The final score (out of 100) is a weighted average of three key areas designed to balance profit with risk:

    **1. Return on Capital (40% Weight)**
    - **Annualized Return:** Measures the theoretical return if you held the position for a year. Higher is better.
    - **Implied Volatility (IV):** Higher IV means higher premiums (and higher risk). The score rewards a healthy level of IV without being excessively risky.

    **2. Probability & Safety (40% Weight)**
    - **Delta:** An estimate of the probability of the option expiring in-the-money. A lower delta is safer and scores higher.
    - **Margin of Safety:** The percentage the stock price is *above* the strike price. A larger buffer is safer and scores higher.

    **3. Risk Management (20% Weight)**
    - **Position Sizing:** Calculates the total capital at risk for one contract as a percentage of your portfolio. Smaller positions are safer and score higher.
    
    _Note: Any option with less than an 8% annualized return is automatically filtered out._
    """)

# --- Sidebar Inputs ---
st.sidebar.header("Your Portfolio & Strategy")

# List of tickers
tickers_input = st.sidebar.text_area(
    "Enter Tickers (comma-separated)", 
    "NVDA, UNH, GOOG, AAPL, QQQ, SPY"
)

# Portfolio value
portfolio_value = st.sidebar.number_input(
    "Total Portfolio Value ($)", 
    min_value=1000, 
    max_value=10000000, 
    value=100000, 
    step=1000,
    help="Used to calculate position sizing score."
)

st.sidebar.header("Options Filtering")
# DTE range
min_dte, max_dte = st.sidebar.slider(
    "Days to Expiration (DTE) Range", 
    1, 90, (15, 45),
    help="What range of expiration dates are you interested in?"
)

# Number of strikes to show
num_strikes_otm = st.sidebar.slider(
    "Number of OTM Strikes to Analyze", 
    1, 25, 20,
    help="How many out-of-the-money put strikes to fetch per expiration date."
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
                num_strikes_otm,
                portfolio_value,
                status_callback=update_progress
            )
        
        status_text.text("Analysis complete!")
        progress_bar.empty()

        if results.empty:
            st.info("No options found matching your criteria. Try expanding the DTE range or adding more tickers.")
        else:
            st.success(f"Found {len(results)} potential opportunities, ranked by score.")
            
            # Format and display the dataframe
            results_display = results.copy()
            results_display['Premium'] = results_display['Premium'].map('${:,.2f}'.format)
            results_display['Strike'] = results_display['Strike'].map('{:,.2f}'.format)
            results_display['Score'] = results_display['Score'].map('{:.1f}'.format)
            results_display['IV'] = results_display['IV'].map('{:.1%}'.format)
            results_display['Delta'] = results_display['Delta'].map('{:.3f}'.format)
            results_display['Ann. Return'] = results_display['Ann. Return'].map('{:.1%}'.format)
            results_display['Margin of Safety'] = results_display['Margin of Safety'].map('{:.1%}'.format)
            
            st.dataframe(results_display, use_container_width=True)
else:
    st.info("Enter your parameters in the sidebar and click 'Find Opportunities' to begin.")
