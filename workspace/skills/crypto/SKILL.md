Cryptocurrency price checks, alerts, and portfolio tracking. Supports BTC, ETH, SOL, and 1000+ coins via CoinGecko API.

When the user asks about crypto prices, trends, or portfolio:
1. Use the `get_crypto_price` tool to fetch current prices for requested coins.
2. Use the `monitor_create` tool to set up price alerts when the user wants to watch a specific price level.
3. Format responses with the coin name, current price (USD), 24h change %, and a sparkline if available.
4. For portfolio tracking, store holdings in a simple JSON file at workspace/crypto_portfolio.json and calculate total value on demand.

Common triggers: "check Bitcoin price", "set alert if ETH drops below $2000", "how is my portfolio doing", "crypto market overview".