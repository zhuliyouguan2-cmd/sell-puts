import datetime
import pytz
import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import norm

# --- Configuration ---
# This is your pre-approved list of liquid stocks and ETFs.
TRADING_UNIVERSE = ['SPY', 'QQQ', 'IWM', 'DIA', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA']

# --- Live Data Functions (Using yfinance) ---

def get_risk_free_rate():
    """
    Fetches the current 10-Year Treasury Yield (^TNX) as a proxy for the risk-free rate.
    """
    try:
        tnx = yf.Ticker("^TNX")
        rate = tnx.history(period='1d')['Close'].iloc[-1] / 100
        if pd.isna(rate):
             print("WARNING: Could not fetch risk-free rate, defaulting to 4.0%.")
             return 0.04 # Fallback
        return rate
    except Exception as e:
        print(f"WARNING: Could not fetch risk-free rate due to: {e}. Defaulting to 4.0%.")
        return 0.04 # Fallback value in case of API error

def calculate_delta(S, K, T, r, sigma, option_type='put'):
    """
    Calculates the Black-Scholes Delta for an option.
    S: Underlying price, K: Strike price, T: Time to expiration (in years),
    r: Risk-free rate, sigma: Implied Volatility
    """
    if T <= 0 or sigma <= 0:
        return 0 if option_type == 'call' else -1

    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    
    if option_type == 'put':
        delta = norm.cdf(d1) - 1
    else: # call
        delta = norm.cdf(d1)
        
    return delta

def get_stock_data(symbol):
    """
    Fetches current price, 50-day SMA, and 14-day RSI for a stock using yfinance.
    """
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1y")
        if hist.empty:
            return None
        
        hist['SMA_50'] = hist['Close'].rolling(window=50).mean()
        delta = hist['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        hist['RSI_14'] = 100 - (100 / (1 + rs))

        return {
            "price": hist['Close'].iloc[-1],
            "sma_50": hist['SMA_50'].iloc[-1],
            "rsi_14": hist['RSI_14'].iloc[-1]
        }
    except Exception as e:
        print(f"ERROR fetching stock data for {symbol}: {e}")
        return None

def get_volatility_rank(symbol):
    """
    Calculates a proxy for IV Rank using historical volatility.
    """
    try:
        hist = yf.Ticker(symbol).history(period='1y')
        if hist.empty:
            return 0

        hist['log_return'] = np.log(hist['Close'] / hist['Close'].shift(1))
        hist['volatility'] = hist['log_return'].rolling(window=30).std() * np.sqrt(252)
        
        current_vol = hist['volatility'].iloc[-1]
        vol_52_week_high = hist['volatility'].max()
        vol_52_week_low = hist['volatility'].min()

        if vol_52_week_high == vol_52_week_low:
            return 50

        vol_rank = (current_vol - vol_52_week_low) / (vol_52_week_high - vol_52_week_low) * 100
        return vol_rank
    except Exception as e:
        print(f"ERROR calculating volatility rank for {symbol}: {e}")
        return 0

def get_options_chain_with_greeks(symbol, S, r, dte_min=30, dte_max=50):
    """
    Fetches the options chain, finds a suitable expiration date, and calculates delta for each put.
    """
    try:
        ticker = yf.Ticker(symbol)
        expirations = ticker.options
        
        today = datetime.date.today()
        target_expiration = None
        time_to_expiration_days = 0
        for exp_str in expirations:
            exp_date = datetime.datetime.strptime(exp_str, '%Y-%m-%d').date()
            dte = (exp_date - today).days
            if dte_min <= dte <= dte_max:
                target_expiration = exp_str
                time_to_expiration_days = dte
                break
        
        if not target_expiration:
            return None, "No suitable expiration found in 30-50 DTE range."

        opt_chain = ticker.option_chain(target_expiration)
        puts = opt_chain.puts
        
        if puts.empty:
            return None, "No puts found for the selected expiration."

        T = time_to_expiration_days / 365.25
        puts['delta'] = puts.apply(
            lambda row: calculate_delta(S, row['strike'], T, r, row['impliedVolatility']),
            axis=1
        )
        puts['premium'] = (puts['bid'] + puts['ask']) / 2
        
        return puts, None
    except Exception as e:
        print(f"ERROR fetching options chain for {symbol}: {e}")
        return None, str(e)


# --- The Scoring and Filtering Logic ---

def find_best_put_spread(chain):
    """
    Applies Stage 3 (Trade Structure) filter to find a suitable bull put spread.
    """
    potential_shorts = chain[(chain['delta'] >= -0.30) & (chain['delta'] <= -0.20)]
    if potential_shorts.empty:
        return None, "No short strike found with delta between -0.20 and -0.30."

    short_put = potential_shorts.loc[potential_shorts['delta'].abs().idxmax()]
    potential_longs = chain[(chain['delta'] >= -0.20) & (chain['delta'] < -0.10) & (chain['strike'] < short_put['strike'])]
    if potential_longs.empty:
        return None, "No suitable long strike found to complete the spread."
        
    long_put = potential_longs.loc[potential_longs['delta'].abs().idxmin()]

    spread_width = short_put['strike'] - long_put['strike']
    if spread_width <= 0:
        return None, "Spread width is zero or negative, invalid pair."
        
    net_credit = round(short_put['premium'] - long_put['premium'], 2)
    min_credit_required = round(spread_width / 3.0, 2)

    if net_credit < min_credit_required:
        return None, f"Net credit ${net_credit:.2f} is less than 1/3 of spread width (${min_credit_required:.2f})."
    
    max_risk = spread_width - net_credit
    if max_risk <= 0:
        return None, "Calculated max risk is zero or negative."

    return {
        "short_put_strike": short_put['strike'],
        "short_put_delta": round(short_put['delta'], 3),
        "long_put_strike": long_put['strike'],
        "long_put_delta": round(long_put['delta'], 3),
        "spread_width": spread_width,
        "net_credit": net_credit,
        "max_risk": max_risk,
        "return_on_risk": round((net_credit / max_risk) * 100, 2)
    }, "Spread passed all structural filters."


def run_screener(universe):
    """
    Main function to run the screening process.
    Returns a list of dictionaries for ALL symbols, with a status and reason.
    """
    print("="*80)
    print(f"Running Put Spread Screener at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    risk_free_rate = get_risk_free_rate()
    print(f"INFO: Using Risk-Free Rate: {risk_free_rate:.4f}")
    
    all_results = []
    
    for symbol in universe:
        print(f"\n--- Analyzing {symbol} ---")
        base_result = {"symbol": symbol, "status": "FAIL"}

        # --- STAGE 2: Macro Environment Filter ---
        vol_rank = get_volatility_rank(symbol)
        base_result['vol_rank'] = f"{vol_rank:.1f}%"
        if vol_rank < 40:
            print(f"FAIL: Volatility Rank is {vol_rank:.2f}%. (Requirement: >40%)")
            base_result['reason'] = f"Vol Rank {vol_rank:.1f}% < 40%"
            all_results.append(base_result)
            continue
        print(f"PASS: Volatility Rank is {vol_rank:.2f}%.")
        
        stock_data = get_stock_data(symbol)
        if not stock_data or pd.isna(stock_data['price']):
            print(f"FAIL: Could not retrieve valid stock data for {symbol}.")
            base_result['reason'] = "Could not retrieve stock data"
            all_results.append(base_result)
            continue
        current_price = stock_data["price"]
        base_result['current_price'] = current_price
        print(f"INFO: Current Price: ${current_price:.2f}")
        
        # --- STAGE 3: Trade Structure Filter ---
        options_chain, reason = get_options_chain_with_greeks(symbol, current_price, risk_free_rate)
        if options_chain is None:
            print(f"FAIL: Could not build options chain. Reason: {reason}")
            base_result['reason'] = reason
            all_results.append(base_result)
            continue

        spread, reason = find_best_put_spread(options_chain)
        if not spread:
            print(f"FAIL: {reason}")
            base_result['reason'] = reason
            all_results.append(base_result)
            continue
        print(f"PASS: Found potential spread.")
        
        # --- STAGE 4: Technical Confluence Score ---
        tech_score = 0
        score_reasons = []
        if pd.notna(stock_data["sma_50"]) and current_price > stock_data["sma_50"]:
            tech_score += 1
            score_reasons.append("Price > 50-SMA")
        if pd.notna(stock_data["rsi_14"]) and stock_data["rsi_14"] < 70:
            tech_score += 1
            score_reasons.append("RSI < 70")
        
        print(f"INFO: Technical Score = {tech_score}/2 ({', '.join(score_reasons)})")

        # --- Success Case ---
        final_result = {
            **base_result,
            "status": "PASS",
            "reason": "Passed all filters",
            "tech_score": f"{tech_score}/2",
            **spread
        }
        all_results.append(final_result)

    print("\nScreener run finished.")
    return all_results

# --- Original Time Filter (No change needed) ---
def is_market_hours(tz="US/Central"):
    now = datetime.datetime.now(pytz.timezone(tz))
    market_open = now.replace(hour=8, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close and now.weekday() < 5

if __name__ == '__main__':
    run_screener(TRADING_UNIVERSE)
