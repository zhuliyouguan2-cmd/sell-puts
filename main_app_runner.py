import time
import datetime
from options_screener_logic import run_screener, is_market_hours, TRADING_UNIVERSE

def main():
    """
    Main loop to run the screener on a schedule during trading hours.
    """
    # Run immediately on start if market is open
    if is_market_hours():
        print("Market is open. Running initial scan...")
        run_screener(TRADING_UNIVERSE)
    else:
        print(f"Market is currently closed. Waiting for market open... Current time: {datetime.datetime.now().strftime('%H:%M:%S')}")

    while True:
        # Wait for 1.5 hours before the next check
        print(f"\nNext scan scheduled in 1.5 hours at {(datetime.datetime.now() + datetime.timedelta(hours=1.5)).strftime('%H:%M:%S')}")
        time.sleep(90 * 60) # 90 minutes * 60 seconds

        if is_market_hours():
            run_screener(TRADING_UNIVERSE)
        else:
            print(f"Market is currently closed. No scan was run. Current time: {datetime.datetime.now().strftime('%H:%M:%S')}")
            # Optional: Add a shorter sleep here if you want it to check more frequently
            # when the market is about to open, but for now it will just wait another 1.5 hours.

if __name__ == "__main__":
    main()
