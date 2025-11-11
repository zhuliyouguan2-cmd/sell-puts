import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import norm
import datetime
import streamlit as st
# import requests # No longer needed, pd.read_html handles it

# --- Caching ---
@st.cache_data(ttl=86400) # Cache for 1 day
def get_ndx_tickers():
    """
    Fetches the list of NASDAQ-100 tickers from Wikipedia.
    """
    # try:
    #     url = 'https://en.wikipedia.org/wiki/NASDAQ-100'
    #     # pd.read_html needs lxml or beautifulsoup4 installed
    #     tables = pd.read_html(url)
    #     # Find the correct table. It's usually the 4th or 5th one.
    #     # We look for one that has "Ticker" and "Company" columns.
    #     ndx_table = None
    #     for table in tables:
    #         if 'Ticker' in table.columns and 'Company' in table.columns:
    #             ndx_table = table
    #             break
        
    #     if ndx_table is None:
    #         print("Could not find NASDAQ-100 ticker table on Wikipedia.")
    #         return []
            
    #     # The ticker list may contain non-standard tickers (e.g., 'BRK.B').
    #     # yfinance can handle most of them.
    #     tickers = ndx_table['Ticker'].tolist()
    #     return tickers
    # except Exception as e:
    #     print(f"Error fetching NDX tickers: {e}")
        # Fallback list in case Wikipedia scrape fails
    return [
    "AAPL", "ABNB", "ADBE", "ADI", "ADP", "ADSK", "AEP", "AMAT",
    "AMD", "AMGN", "AMZN", "APP", "ARM", "ASML", "AVGO", "AXON",
    "AZN", "BIIB", "BKNG", "BKR", "CCEP", "CDNS", "CDW", "CEG",
    "CHTR", "CMCSA", "COST", "CPRT", "CRWD", "CSCO", "CSGP", "CSX",
    "CTAS", "CTSH", "DASH", "DDOG", "DXCM", "EA", "EXC", "FANG",
    "FAST", "FTNT", "GEHC", "GFS", "GILD", "GOOG", "GOOGL", "HON",
    "IDXX", "INTC", "INTU", "ISRG", "KDP", "KHC", "KLAC", "LIN",
    "LRCX", "LULU", "MAR", "MCHP", "MDLZ", "MELI", "META", "MNST",
    "MRVL", "MSFT", "MSTR", "MU", "NFLX", "NVDA", "NXPI", "ODFL",
    "ON", "ORLY", "PANW", "PAYX", "PCAR", "PDD", "PEP", "PLTR",
    "QCOM", "REGN", "ROKU", "SBUX", "SGEN", "SIRI", "SNOW", "SPLK",
    "TTWO", "TXN", "UAL", "VRTX", "WDAY", "XEL", "XLNX", "ZM"] # Add more if you like

@st.cache_data(ttl=86400) # Cache for 1 hour
def get_market_breadth():
    """
    Calculates market breadth for NASDAQ-100.
    - % stocks > MA20
    - % stocks > MA50
    - % stocks > MA200
    """
    try:
        tickers = get_ndx_tickers()
        if not tickers:
            return None

        # Download data for all tickers at once. 201 days for 200-day MA.
        data = yf.download(tickers, period="201d", auto_adjust=True)['Close']
        
        if data.empty:
            return None

        # Get the latest price for each stock
        latest_price = data.iloc[-1]

        # Calculate MAs for all stocks
        ma20 = data.rolling(window=20).mean().iloc[-1]
        ma50 = data.rolling(window=50).mean().iloc[-1]
        ma200 = data.rolling(window=200).mean().iloc[-1]

        # Count how many stocks are above their MAs
        # .count() gives the number of non-NaN values, which is our true total
        breadth_20 = (latest_price > ma20).sum() / ma20.count() * 100
        breadth_50 = (latest_price > ma50).sum() / ma50.count() * 100
        breadth_200 = (latest_price > ma200).sum() / ma200.count() * 100
        
        return {
            'breadth_20': breadth_20,
            'breadth_50': breadth_50,
            'breadth_200': breadth_200,
            'count': len(tickers) # Total tickers attempted
        }
    except Exception as e:
        print(f"Error in get_market_breadth: {e}")
        return None

@st.cache_data(ttl=900)
def get_stock_data_and_technicals(ticker):
    """
    Fetches serializable stock data, calculates technicals, and historical volatility range.
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        # Fetch 1 year of data for HV calculation
        hist = stock.history(period="1y")

        if hist.empty or len(hist) < 30: # Need at least 30 days for rolling HV
            return None, None, None, None, None, None, None, None

        price = hist['Close'].iloc[-1]
        sector = info.get('sector', 'N/A')
        expirations = stock.options

        # --- Calculate Historical Volatility (HV) Range for IV Rank Proxy ---
        log_returns = np.log(hist['Close'] / hist['Close'].shift(1))
        # 30-day rolling annualized volatility
        rolling_hv = log_returns.rolling(window=30).std() * np.sqrt(252)
        hv_low_1y = rolling_hv.min()
        hv_high_1y = rolling_hv.max()

        # --- Calculate Technical Indicators ---
        delta_hist = hist['Close'].diff()
        gain = (delta_hist.where(delta_hist > 0, 0)).rolling(window=14).mean()
        loss = (-delta_hist.where(delta_hist < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1] if pd.notna(rsi.iloc[-1]) else 50

        sma_50 = hist['Close'].rolling(window=50).mean().iloc[-1]
        sma_200 = hist['Close'].rolling(window=200).mean().iloc[-1]

        return price, sector, expirations, current_rsi, sma_50, sma_200, hv_low_1y, hv_high_1y
    except Exception as e:
        print(f"Error fetching data for {ticker}: {e}")
        return None, None, None, None, None, None, None, None


@st.cache_data(ttl=900)
def get_options_chain_puts(ticker, expiration):
    """Fetches the put options DataFrame for a specific ticker and expiration date."""
    try:
        stock = yf.Ticker(ticker)
        options = stock.option_chain(expiration)
        return options.puts
    except Exception:
        return None

# --- *** NEW QQQ STATUS FUNCTION (ADDED) *** ---
@st.cache_data(ttl=900)
def get_qqq_status():
    """
    Fetches QQQ data and calculates weekly EMAs based on the strategy.
    Returns a dictionary with current price and EMA values.
    """
    try:
        # We need ~2 years of data for the 104-week (520-day) EMA
        start_date = (datetime.date.today() - datetime.timedelta(days=730)).strftime('%Y-%m-%d')
        
        # Download data, setting auto_adjust=False to get 'Adj Close'
        df = yf.download('QQQ', start=start_date, auto_adjust=False)
        
        if df.empty:
            print("Error: No data downloaded for QQQ.")
            return None
            
        # Standardize columns (handles 'open' vs 'Open' and MultiIndex)
        df.columns = [col[0].title() if isinstance(col, tuple) else col.title() for col in df.columns]
        df = df.loc[~df.index.duplicated(keep='first')]
        df.sort_index(inplace=True)

        # Calculate EMAs on 'Adj Close' (price adjusted for splits/dividends)
        # 26 weeks * 5 days/week = 130 days
        # 52 weeks * 5 days/week = 260 days
        # 104 weeks * 5 days/week = 520 days
        df['EMA26'] = df['Adj Close'].ewm(span=130, adjust=False).mean()
        df['EMA52'] = df['Adj Close'].ewm(span=260, adjust=False).mean()
        df['EMA104'] = df['Adj Close'].ewm(span=520, adjust=False).mean()
        
        # Get the very last row of data
        latest_data = df.iloc[-1]
        
        # Get current price (most recent 'Adj Close')
        current_price = latest_data['Adj Close']
        
        status = {
            'current_price': current_price,
            'ema_26': latest_data['EMA26'],
            'ema_52': latest_data['EMA52'],
            'ema_104': latest_data['EMA104']
        }
        return status
        
    except Exception as e:
        print(f"Error in get_qqq_status: {e}")
        return None
# --- *** END OF NEW FUNCTION *** ---


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
    if best < worst: # Lower is better
        worst, best = best, worst
        value = max(worst, min(best, value)) # Clamp
        score = 5 * (best - value) / (best - worst)
    else: # Higher is better
        value = max(worst, min(best, value)) # Clamp
        score = 5 * (value - worst) / (best - worst)
    return score

# --- Scoring Logic ---
def score_option(option, current_price, portfolio_value, sector, rsi, sma_50, sma_200, hv_low_1y, hv_high_1y):
    """Scores a single put option using continuous linear functions and IV Rank."""
    strike = option['strike']
    premium = option['bid']
    iv = option['impliedVolatility']
    dte = (datetime.datetime.strptime(option['expirationDate'], '%Y-%m-%d') - datetime.datetime.now()).days
    
    if dte <= 0 or premium <= 0 or strike <= 0:
        return None

    capital_at_risk_per_share = strike - premium
    annualized_return = (premium / capital_at_risk_per_share) * (365 / dte) if capital_at_risk_per_share > 0 else 0
    if annualized_return < 0.08:
        return None

    # Calculate IV Rank
    iv_range = hv_high_1y - hv_low_1y
    if iv_range > 0:
        iv_rank = (iv - hv_low_1y) / iv_range
    else:
        iv_rank = 0.5 # Default to neutral if no range
    iv_rank = max(0, min(1, iv_rank)) # Clamp between 0 and 1

    # 1. Return on Capital (45% Weight)
    score_ar = linear_scale(annualized_return, worst=0.08, best=0.25)
    score_iv_rank = linear_scale(iv_rank, worst=0.10, best=0.80) # Score based on IV Rank
    score_return_on_capital = (score_ar + score_iv_rank) / 2

    # 2. Probability & Safety (35% Weight)
    T = dte / 365.0
    r = 0.04 
    delta = black_scholes_put_delta(current_price, strike, T, r, iv)
    abs_delta = abs(delta)
    score_delta = linear_scale(abs_delta, worst=0.35, best=0.10) # Lower is better
    margin_of_safety = (current_price - strike) / current_price
    score_mos = linear_scale(margin_of_safety, worst=0.05, best=0.20)
    score_prob_safety = (score_delta + score_mos) / 2

    # 3. Basic Technical Indicators (15% Weight)
    score_rsi = linear_scale(rsi, worst=65, best=35) # Lower is better
    price_vs_sma_pct = (current_price - sma_200) / sma_200
    score_sma = linear_scale(price_vs_sma_pct, worst=0.0, best=0.15)
    score_technicals = (score_rsi + score_sma) / 2

    # 4. Risk Management (5% Weight)
    capital_at_risk_total = (strike * 100) - (premium * 100)
    risk_as_pct_portfolio = (capital_at_risk_total / portfolio_value) * 100 if portfolio_value > 0 else float('inf')
    score_sizing = linear_scale(risk_as_pct_portfolio, worst=10.0, best=1.0) # Lower is better

    # Final Score Calculation
    final_score = ((score_return_on_capital * 0.45) + \
                    (score_prob_safety * 0.35) + \
                    (score_technicals * 0.15) + \
                    (score_sizing * 0.05)) / 5 * 100
    
    return {
        'Expiration': option['expirationDate'], 'Strike': strike, 'Premium': premium,
        'DTE': dte, 'IV Rank': iv_rank, 'Delta': delta, 'Ann. Return': annualized_return,
        'Margin of Safety': margin_of_safety, 'Score': final_score,
        'Ticker': option['ticker'], 'Sector': sector
    }

# --- Main Processing Function ---
def process_tickers(tickers, min_dte, max_dte, portfolio_value, status_callback=None):
    all_options = []
    for i, ticker in enumerate(tickers):
        if status_callback:
            status_callback(f"Fetching data for {ticker}...", (i + 1) / len(tickers))

        (current_price, sector, expirations, rsi, sma_50, sma_200, 
         hv_low_1y, hv_high_1y) = get_stock_data_and_technicals(ticker)

        if current_price is None or not expirations:
            print(f"Skipping {ticker} due to missing data.")
            continue

        valid_expirations = [exp for exp in expirations if min_dte <= (datetime.datetime.strptime(exp, '%Y-%m-%d') - datetime.datetime.now()).days <= max_dte]

        for exp in valid_expirations:
            puts = get_options_chain_puts(ticker, exp)
            if puts is None or puts.empty: continue
            puts['ticker'] = ticker
            puts['expirationDate'] = exp
            otm_puts = puts[puts['strike'] < current_price]

            for _, row in otm_puts.iterrows():
                score_data = score_option(row, current_price, portfolio_value, sector, 
                                          rsi, sma_50, sma_200, hv_low_1y, hv_high_1y)
                if score_data:
                    all_options.append(score_data)
        
    if not all_options:
        return pd.DataFrame()

    df = pd.DataFrame(all_options)
    
    # Define the desired column order with Ticker first and IV Rank instead of IV
    column_order = [
        'Ticker', 'Expiration', 'Strike', 'Premium', 'Score', 'Ann. Return', 
        'Margin of Safety', 'DTE', 'IV Rank', 'Delta', 'Sector'
    ]
    df = df.reindex(columns=column_order)

    return df.sort_values(by='Score', ascending=False).reset_index(drop=True)
