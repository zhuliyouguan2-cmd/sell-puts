import streamlit as st
import pandas as pd
# --- MODIFIED IMPORT ---
# We now also import 'get_qqq_status' (which you will add to your backend.py)
from backend import process_tickers, get_qqq_status 

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
    /* Style for the QQQ Dashboard metrics */
    .st-emotion-cache-1g6gooi { 
        border: 1px solid rgba(255, 255, 255, 0.2);
        border-radius: 0.5rem;
        padding: 1rem;
    }
    </style>
""", unsafe_allow_html=True)

st.title("📈 Value Investor's Put Option Screener")
st.markdown("Find attractive put-selling opportunities based on your pre-vetted list of stocks.")

# --- Scoring Logic Expander ---
with st.expander("How are these options scored?"):
    st.markdown("""
    The final score (out of 100) is a weighted average of four key areas:

    **1. Return on Capital**
    - **Annualized Return:** The theoretical return if you held the position for a year.
    - **Implied Volatility (IV):** Rewards a healthy level of IV for higher premiums.

    **2. Probability & Safety**
    - **Delta:** A lower delta (lower probability of expiring in-the-money) is safer and scores higher.
    - **Margin of Safety:** The percentage the stock price is *above* the strike price. A larger buffer is safer.

    **3. Basic Technicals**
    - **Relative Strength Index (RSI):** Favors stocks that are not in "overbought" territory.
    - **Simple Moving Average (SMA):** Rewards stocks trading above their 50-day and 200-day moving averages, indicating a healthy uptrend.

    **4. Risk Management**
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
        
        # --- *** NEW QQQ DASHBOARD SECTION *** ---
        # If QQQ is in the list, show the strategy dashboard
        if 'QQQ' in tickers_list:
            st.subheader("QQQ Deployment Strategy Dashboard")
            try:
                with st.spinner("Analyzing QQQ Weekly EMA status..."):
                    qqq_status = get_qqq_status() 
                
                if qqq_status:
                    price = qqq_status['current_price']
                    ema_26 = qqq_status['ema_26']
                    ema_52 = qqq_status['ema_52']
                    ema_104 = qqq_status['ema_104']

                    st.metric("QQQ Current Price", f"${price:,.2f}")

                    col1, col2, col3 = st.columns(3)
                    
                    # --- EMA 26 ---
                    col1.metric("26-Week EMA (130d)", f"${ema_26:,.2f}")
                    if price <= ema_26:
                        col1.error("🚨 TRIGGER 1: Deploy 20%")
                    else:
                        col1.success(f"Price is ${price - ema_26:,.2f} above.")
                    
                    # --- EMA 52 ---
                    col2.metric("52-Week EMA (260d)", f"${ema_52:,.2f}")
                    if price <= ema_52:
                        col2.error("🚨 TRIGGER 2: Deploy 50% Rem.")
                    else:
                        col2.success(f"Price is ${price - ema_52:,.2f} above.")

                    # --- EMA 104 ---
                    col3.metric("104-Week EMA (520d)", f"${ema_104:,.2f}")
                    if price <= ema_104:
                        col3.error("🚨 TRIGGER 3: Deploy 80% Rem.")
                    else:
                        col3.success(f"Price is ${price - ema_104:,.2f} above.")
                    
                    st.markdown("---") # Add a separator
                else:
                    st.warning("Could not retrieve QQQ status.")
            except Exception as e:
                st.error(f"Error fetching QQQ status. Make sure 'get_qqq_status' function is in backend.py. Error: {e}")
        # --- *** END OF NEW SECTION *** ---

        # --- Existing Options Screener Logic ---
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
