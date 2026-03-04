"""
Pytest configuration — runs before any test file is imported.
Sets dummy env vars so bot.py can be imported without a real .env file.
"""

import os

os.environ.setdefault("DISCORD_TOKEN", "test_discord_token")
os.environ.setdefault("NEWS_API_KEY", "test_newsdata_key")
