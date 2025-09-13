import streamlit as st
import pandas as pd
from backend import process_tickers # Import the main function from the backend

# --- Streamlit UI ---
st.set_page_config(layout="wide")
st.title("Value Investor's Put Option Screener")
st.markdown("""
This tool helps value investors find attractive put options to sell on their pre-approved list of stocks. 
It scores options based on profitability, safety, and risk management.
""")

with st.sidebar:
    st.header("Your Portfolio Settings")
    portfolio_value = st.number_input("Total Portfolio Value ($)", min_value=10000, value=100000, step=10000)
    max_sector_exposure_pct = st.slider("Max Desired Sector Exposure (%)", min_value=5, max_value=50, value=20, step=1)
    
    st.header("Options Filtering")
    min_dte = st.slider("Minimum Days to Expiration (DTE)", 0, 90, 30)
    max_dte = st.slider("Maximum Days to Expiration (DTE)", 0, 365, 50)
    num_strikes_otm = st.slider("Number of Out-of-the-Money Strikes to Scan", 1, 20, 10)

tickers_input = st.text_area("Enter tickers you are willing to own, separated by commas or new lines", "NVDA, UNH, GOOG, AAPL, QQQ, SPY")

if st.button("Find Top Put Options"):
    tickers = [ticker.strip().upper() for ticker in tickers_input.replace(',', '\n').split() if ticker.strip()]
    
    if not tickers:
        st.warning("Please enter at least one ticker.")
    else:
        progress_bar = st.progress(0)
        status_text = st.empty()

        # Define a callback function to update the UI from the backend
        def update_progress(message, progress):
            status_text.text(message)
            progress_bar.progress(progress)

        # Call the backend to do all the work
        df_sorted = process_tickers(
            tickers, 
            min_dte, 
            max_dte, 
            num_strikes_otm, 
            portfolio_value, 
            max_sector_exposure_pct,
            status_callback=update_progress
        )
        
        status_text.text("Scoring complete!")

        if df_sorted.empty:
            st.warning("No suitable options found with the current filters. Try adjusting DTE or the number of strikes.")
        else:
            # Format the dataframe for display
            df_display = df_sorted.copy()
            df_display['Score'] = df_display['Score'].map('{:,.1f}'.format)
            df_display['Strike'] = df_display['Strike'].map('${:,.2f}'.format)
            df_display['Premium'] = df_display['Premium'].map('${:,.2f}'.format)
            df_display['Ann. Return'] = pd.to_numeric(df_display['Ann. Return']).map('{:.2%}'.format)
            df_display['IV'] = pd.to_numeric(df_display['IV']).map('{:.2%}'.format)
            df_display['Margin of Safety'] = pd.to_numeric(df_display['Margin of Safety']).map('{:.2%}'.format)
            df_display['Delta'] = df_display['Delta'].map('{:.3f}'.format)

            st.dataframe(df_display[[
                'Ticker', 'Expiration', 'Strike', 'Premium', 'Score', 'Ann. Return', 
                'Margin of Safety', 'Delta', 'DTE', 'IV', 'Sector'
            ]], use_container_width=True)
