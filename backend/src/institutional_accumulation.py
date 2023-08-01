from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.common.exceptions import InvalidSessionIdException
import threading
from typing import Dict
from utils.logging import *
from utils.outfiles import *
from utils.scraping import *
from utils.concurrency import *

# constants
threads = 5  # number of concurrent Selenium browser instances to fetch data
timeout = 60
inflows_xpath = "/html/body/div[2]/main/div[2]/article/form/div[4]/div[2]/div[2]/div[1]/div[2]/div/div/div[2]/div/svg/g[3]/g[4]/text[1]/tspan[2]"
outflows_xpath = "/html/body/div[2]/main/div[2]/article/form/div[4]/div[2]/div[2]/div[1]/div[2]/div/div/div[2]/div/svg/g[3]/g[4]/text[3]/tspan[2]"

# print header message to terminal
process_name = "Institutional Accumulation"
process_stage = 5
print_status(process_name, process_stage, True)

# logging data (printed to console after screen finishes)
logs = []

# retreive JSON data from previous screen iteration
df = open_outfile("revenue_growth")

# populate these lists while iterating through symbols
successful_symbols = []
failed_symbols = []
drivers = []

# store local thread data
thread_local = threading.local()


def fetch_institutional_holdings(symbol: str) -> Dict[str, float]:
    "Fetch institutional holdings data for a stock symbol from nasdaq.com."
    # perform get request and stop loading page when data is detected in DOM
    url = f"https://www.marketbeat.com/stocks/NASDAQ/{symbol}/institutional-ownership/"

    driver = get_driver(thread_local, drivers)
    driver.get(url)

    wait_methods = [
        element_is_float(inflows_xpath),
        element_is_float(outflows_xpath),
    ]

    combined_wait_method = WaitForAll(wait_methods)

    try:
        WebDriverWait(driver, timeout).until(combined_wait_method)
        driver.execute_script("window.stop();")
    except TimeoutException:
        logs.append(skip_message(symbol, "request timed out"))
        return None

    # extract institutional holdings information from DOM
    try:
        inflows = extract_dollars(driver.find_element(By.XPATH, inflows_xpath))
        outflows = extract_dollars(driver.find_element(By.XPATH, outflows_xpath))
    except Exception as e:
        logs.append(skip_message(symbol, e))
        return None

    if (inflows is None) or (outflows is None):
        logs.append(skip_message(symbol, "insufficient data"))
        return None

    return {"Inflows": inflows, "Outflows": outflows}


def screen_institutional_accumulation(df_index: int) -> None:
    """Populate stock data lists based on whether the given dataframe row is experiencing institutional demand."""
    # extract stock information from dataframe and fetch institutional holdings info
    row = df.iloc[df_index]

    symbol = row["Symbol"]
    holdings_data = fetch_institutional_holdings(symbol)

    # check for failed GET requests
    if holdings_data is None:
        failed_symbols.append(symbol)
        return

    net_inflows = holdings_data["Inflows"] - holdings_data["Outflows"]

    # add institutional holdings info to logs
    logs.append(
        f"""\n{symbol} | Net Institutional Inflows (most recent Q): ${net_inflows / 1000000:.2f}M 
        Inflows: ${holdings_data["Inflows"] / 1000000:.2f}M, Outflows: ${holdings_data["Outflows"] / 1000000:.2f}M\n"""
    )

    # filter out stocks which are not under institutional accumulation
    if net_inflows < 0:
        logs.append(filter_message(symbol))
        return

    successful_symbols.append(
        {
            "Symbol": symbol,
            "Company Name": row["Company Name"],
            "Industry": row["Industry"],
            "RS": row["RS"],
            "Price": row["Price"],
            "Market Cap": row["Market Cap"],
            "Net Institutional Inflows": net_inflows,
            "Revenue Growth % (most recent Q)": row["Revenue Growth % (most recent Q)"],
            "Revenue Growth % (previous Q)": row["Revenue Growth % (previous Q)"],
            "50-day Average Volume": row["50-day Average Volume"],
            "% Below 52-week High": row["% Below 52-week High"],
        }
    )


# launch concurrent worker threads to execute the screen
print("\nFetching institutional holdings data . . .\n")
tqdm_thread_pool_map(threads, screen_institutional_accumulation, range(0, len(df)))

# close Selenium web driver sessions
print("\nClosing browser instances . . .\n")
for driver in tqdm(drivers):
    driver.quit()

# create a new dataframe with symbols which satisfied trend criteria
screened_df = pd.DataFrame(successful_symbols)

# serialize data in JSON format and save on machine
create_outfile(screened_df, "institutional_accumulation")

# print log
print("".join(logs))

# print footer message to terminal
print(f"{len(failed_symbols)} symbols failed (insufficient data).")
print(
    f"{len(df) - len(screened_df) - len(failed_symbols)} symbols filtered (not under institutional accumulation)."
)
print(f"{len(screened_df)} symbols passed.")
print_status(process_name, process_stage, False)
