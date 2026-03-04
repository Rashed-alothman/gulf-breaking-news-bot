# 📰 Gulf Breaking News Bot

A Discord bot that delivers real-time breaking news from **Saudi Arabia** and the **Gulf region** directly into your server, powered by [newsdata.io](https://newsdata.io).

News is posted automatically every 15 minutes, or on-demand using slash commands. Supports both Arabic and English articles.

---

## Features

- **Auto-feed** — posts up to 5 new articles every 15 minutes
- **On-demand fetch** — use `/latest` to get news instantly at any time
- **Keyword search** — use `/search` to find news about a specific topic (e.g. NEOM, oil, Saudi Vision 2030)
- **Per-server setup** — each Discord server picks its own news channel using `/setup`
- **Admin controls** — start and stop the feed without restarting the bot
- **Rich embeds** — articles show title, description, image, source, and publish date
- **Duplicate filtering** — the bot never posts the same article twice

---

## Project Structure

```
Discord_Bot/
├── discord.py        # All bot code lives here (single file)
├── config.json       # Auto-created at runtime — stores each server's news channel ID
├── .env              # Your secret keys (never commit this)
├── .env.example      # Template showing which keys are needed
├── .gitignore        # Excludes .env and config.json from Git
├── requirements.txt  # Python dependencies
├── Procfile          # Tells Railway/Render how to run the bot
└── README.md         # This file
```

---

## How It Works

### The main pieces

**`NewsBot` class** (`discord.py` line 65)
The bot class that extends `commands.Bot`. It holds:
- `seen_ids` — a set of article IDs already posted (prevents duplicates)
- `session` — a single shared `aiohttp` HTTP session (created once, reused every fetch)
- `guild_config` — a dictionary loaded from `config.json` mapping each server to its news channel

**`auto_fetch` loop** (line 142)
Runs every 15 minutes. For each server that has a news channel set up, it fetches articles from newsdata.io, filters out ones already seen, and posts the new ones oldest-first so the channel reads chronologically.

**`fetch_articles()` method** (line 108)
The single place that talks to the newsdata.io API. Used by both the auto loop and the `/latest` and `/search` commands. Handles rate limiting (HTTP 429) and timeouts gracefully.

**`config.json`**
Stores which channel each Discord server uses for news. It looks like this:
```json
{
  "123456789012345678": {
    "channel_id": 987654321098765432
  }
}
```
This file is created automatically when an admin runs `/setup`. It is not committed to Git.

---

## Setup Guide

### 1. Prerequisites

- Python 3.11 or newer
- A [Discord Bot Token](https://discord.com/developers/applications)
- A [newsdata.io API Key](https://newsdata.io) (free tier works)

### 2. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/gulf-breaking-news-bot.git
cd gulf-breaking-news-bot
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create your `.env` file

Copy the example file and fill in your keys:

```bash
cp .env.example .env
```

Then open `.env` and add your real values:

```env
DISCORD_TOKEN=your_discord_bot_token_here
NEWS_API_KEY=your_newsdata_io_api_key_here
```

> **Never share or commit your `.env` file.** It is already excluded by `.gitignore`.

### 5. Invite the bot to your server

In the [Discord Developer Portal](https://discord.com/developers/applications):
1. Go to your application → **OAuth2 → URL Generator**
2. Select scopes: `bot` and `applications.commands`
3. Select permissions: `Send Messages`, `Embed Links`, `View Channels`
4. Copy the generated URL and open it in your browser to invite the bot

### 6. Run the bot

```bash
python discord.py
```

### 7. Set up your news channel in Discord

Go to the channel where you want news to be posted, then run:

```
/setup
```

Then start the automatic feed:

```
/start
```

That's it. The bot will start posting news every 15 minutes.

---

## Commands

| Command | Who can use it | Description |
|---|---|---|
| `/setup` | Admins only | Register the current channel as the news channel |
| `/start` | Admins only | Start the automatic 15-minute news feed |
| `/stop` | Admins only | Stop the automatic feed (does not reset the channel) |
| `/latest` | Everyone | Fetch and post the latest news right now |
| `/search <query>` | Everyone | Search news by keyword (e.g. `NEOM`, `oil prices`) |
| `/status` | Everyone | Show bot status: loop state, last fetch time, articles seen |
| `/help` | Everyone | List all commands |

---

## Hosting Online (Railway or Render)

The `Procfile` in this repo is already configured for both platforms. It tells them to run the bot as a background **worker** process (not a web server).

### Railway

1. Push your code to GitHub
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub repo
3. Select your repo
4. Go to **Variables** and add:
   - `DISCORD_TOKEN`
   - `NEWS_API_KEY`
5. Railway will detect the `Procfile` and deploy automatically

### Render

1. Push your code to GitHub
2. Go to [render.com](https://render.com) → New → **Background Worker**
3. Connect your GitHub repo
4. Set **Build Command** to `pip install -r requirements.txt`
5. Set **Start Command** to `python discord.py`
6. Add environment variables: `DISCORD_TOKEN` and `NEWS_API_KEY`
7. Click **Create Background Worker**

> **Note:** Do not set a `config.json` as a secret on hosting platforms. The bot creates it automatically. However, the file will reset every time the bot redeploys. For production, consider replacing `config.json` with a database (see Contributing section below).

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DISCORD_TOKEN` | Yes | Your Discord bot token from the Developer Portal |
| `NEWS_API_KEY` | Yes | Your newsdata.io API key |

---

## Contributing

Contributions are welcome! Here is how the code is organized so you can get started quickly.

### Getting started

```bash
git clone https://github.com/YOUR_USERNAME/gulf-breaking-news-bot.git
cd gulf-breaking-news-bot
pip install -r requirements.txt
cp .env.example .env
# Fill in your keys in .env
python discord.py
```

### How to add a new slash command

All commands are defined at the bottom of `discord.py`. Each command follows this pattern:

```python
@bot.tree.command(name="mycommand", description="What it does.")
@app_commands.describe(param="Description of the parameter")
async def cmd_mycommand(interaction: discord.Interaction, param: str):
    await interaction.response.send_message("Hello!")
```

After adding a command, restart the bot. The `setup_hook` method calls `await self.tree.sync()` on startup which registers all commands with Discord automatically.

> Slash commands can take up to 1 hour to appear in Discord after syncing, but usually it's instant.

### How to change the fetch interval

Find the `@tasks.loop(minutes=15)` decorator above the `auto_fetch` method and change `15` to whatever interval you want.

### How to add more countries or languages

Find the `fetch_articles` method and update the `params` dictionary:

```python
params = {
    "apikey":   NEWS_API_KEY,
    "country":  "sa,ae,kw,bh,om,qa",  # add more country codes here
    "language": "ar,en",
    "category": category,
    "size":     size,
}
```

Country codes follow the [ISO 3166-1 alpha-2](https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2) standard. newsdata.io supports filtering by `country`, `language`, `category`, and free-text `q` (query).

### Ideas for future improvements

- **Database support** — Replace `config.json` with SQLite or PostgreSQL so channel settings survive redeployments
- **Category filter command** — Let users choose a news category (e.g. business, technology, sports)
- **Language toggle** — Let servers choose Arabic-only or English-only
- **Scheduled digest** — Post a morning/evening summary embed instead of individual articles
- **Role mentions** — Ping a specific role when breaking news is posted

### Commit message style

Please use this format for commit messages:

```
type: short description

Longer explanation if needed.
```

Common types: `feat` (new feature), `fix` (bug fix), `refactor` (code cleanup), `docs` (documentation).

Examples:
```
feat: add /category command for filtering news by topic
fix: prevent duplicate posts when bot restarts
docs: update hosting guide for Render
```

---

## License

MIT — feel free to use, modify, and distribute this project.
