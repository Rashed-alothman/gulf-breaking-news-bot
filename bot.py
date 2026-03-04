"""
Gulf & Saudi Arabia Breaking News Bot
Powered by newsdata.io
"""

import discord
from discord.ext import tasks, commands
from discord import app_commands
import aiohttp
import logging
import os
import json
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
TOKEN        = os.getenv("DISCORD_TOKEN")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
CONFIG_FILE  = "config.json"          # stores channel IDs per guild
BASE_URL     = "https://newsdata.io/api/1/news"
MAX_PER_CYCLE = 5                     # articles per auto-fetch


# ── Persistent guild config (config.json) ──────────────────────────────────────
def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}

def save_config(data: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ── Embed builder ──────────────────────────────────────────────────────────────
def build_embed(article: dict, color: discord.Color = discord.Color.red()) -> discord.Embed:
    pub_date = article.get("pubDate", "")
    embed = discord.Embed(
        title=article.get("title") or "Breaking News",
        url=article.get("link"),
        description=article.get("description") or "No description available.",
        color=color,
    )
    if pub_date:
        embed.set_author(name=f"Published: {pub_date}")
    embed.set_footer(
        text=f"📰 {article.get('source_id', 'Unknown')}  |  🌍 Gulf & Saudi Arabia"
    )
    if article.get("image_url"):
        embed.set_image(url=article["image_url"])
    return embed


# ── Bot ────────────────────────────────────────────────────────────────────────
class NewsBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.seen_ids: set[str] = set()
        self.session: aiohttp.ClientSession | None = None
        self.last_fetch: datetime | None = None
        self.guild_config: dict = load_config()   # {guild_id: {"channel_id": int}}

    # ── Channel helpers ────────────────────────────────────────────────────────
    def get_news_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        gid = str(guild.id)
        cid = self.guild_config.get(gid, {}).get("channel_id")
        return guild.get_channel(cid) if cid else None

    def set_news_channel(self, guild: discord.Guild, channel: discord.TextChannel):
        gid = str(guild.id)
        self.guild_config.setdefault(gid, {})["channel_id"] = channel.id
        save_config(self.guild_config)

    # ── Lifecycle ──────────────────────────────────────────────────────────────
    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        await self.tree.sync()
        self.auto_fetch.start()
        log.info("Slash commands synced. Auto-fetch loop started.")

    async def on_ready(self):
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Gulf & Saudi Arabia | /help",
            )
        )

    async def close(self):
        self.auto_fetch.cancel()
        if self.session:
            await self.session.close()
        await super().close()

    # ── newsdata.io fetch ──────────────────────────────────────────────────────
    async def fetch_articles(
        self,
        *,
        query: str | None = None,
        category: str = "top",
        size: int = 10,
    ) -> list[dict]:
        params = {
            "apikey":   NEWS_API_KEY,
            "country":  "sa,ae",
            "language": "ar,en",
            "category": category,
            "size":     size,
        }
        if query:
            params["q"] = query

        timeout = aiohttp.ClientTimeout(total=15)
        try:
            async with self.session.get(BASE_URL, params=params, timeout=timeout) as resp:
                if resp.status == 429:
                    log.warning("Rate limited by newsdata.io — will retry next cycle.")
                    return []
                if resp.status != 200:
                    log.error("newsdata.io API returned HTTP %s", resp.status)
                    return []
                data = await resp.json()
                self.last_fetch = datetime.now(timezone.utc)
                return data.get("results", [])
        except aiohttp.ClientError as exc:
            log.error("HTTP error fetching news: %s", exc)
            return []

    # ── Auto-fetch loop ────────────────────────────────────────────────────────
    @tasks.loop(minutes=15)
    async def auto_fetch(self):
        for guild in self.guilds:
            channel = self.get_news_channel(guild)
            if not channel:
                continue

            articles = await self.fetch_articles()
            new = [a for a in articles if a.get("article_id") not in self.seen_ids]

            if not new:
                continue

            for article in reversed(new[:MAX_PER_CYCLE]):
                self.seen_ids.add(article.get("article_id", ""))
                try:
                    await channel.send(embed=build_embed(article))
                except discord.HTTPException as exc:
                    log.error("Send failed: %s", exc)

            log.info("[%s] Auto-posted %d article(s).", guild.name, min(len(new), MAX_PER_CYCLE))

    @auto_fetch.before_loop
    async def before_auto_fetch(self):
        await self.wait_until_ready()

    @auto_fetch.error
    async def auto_fetch_error(self, error: Exception):
        log.exception("Auto-fetch loop crashed: %s", error)


# ── Bot instance ───────────────────────────────────────────────────────────────
bot = NewsBot()


# ── /setup ─────────────────────────────────────────────────────────────────────
@bot.tree.command(
    name="setup",
    description="Register this channel as the breaking news channel. (Admin only)",
)
@app_commands.checks.has_permissions(administrator=True)
async def cmd_setup(interaction: discord.Interaction):
    bot.set_news_channel(interaction.guild, interaction.channel)
    embed = discord.Embed(
        title="✅ News Channel Set",
        description=(
            f"{interaction.channel.mention} will now receive Gulf & Saudi breaking news.\n\n"
            f"Use `/start` to begin the automatic feed."
        ),
        color=discord.Color.green(),
    )
    await interaction.response.send_message(embed=embed)
    log.info("News channel set to #%s in '%s'", interaction.channel.name, interaction.guild.name)


# ── /start ─────────────────────────────────────────────────────────────────────
@bot.tree.command(name="start", description="Start the automatic news feed. (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_start(interaction: discord.Interaction):
    channel = bot.get_news_channel(interaction.guild)
    if not channel:
        await interaction.response.send_message(
            "No news channel set. Run `/setup` in your news channel first.", ephemeral=True
        )
        return

    if bot.auto_fetch.is_running():
        await interaction.response.send_message("Feed is already running.", ephemeral=True)
        return

    bot.auto_fetch.start()
    await interaction.response.send_message(
        f"▶️ News feed **started** — posting to {channel.mention} every 15 minutes."
    )


# ── /stop ──────────────────────────────────────────────────────────────────────
@bot.tree.command(name="stop", description="Stop the automatic news feed. (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_stop(interaction: discord.Interaction):
    if not bot.auto_fetch.is_running():
        await interaction.response.send_message("Feed is already stopped.", ephemeral=True)
        return
    bot.auto_fetch.cancel()
    await interaction.response.send_message("⏹️ News feed **stopped**.", ephemeral=True)


# ── /latest ────────────────────────────────────────────────────────────────────
@bot.tree.command(name="latest", description="Fetch and post the latest Gulf & Saudi news right now.")
async def cmd_latest(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    channel = bot.get_news_channel(interaction.guild)
    if not channel:
        await interaction.followup.send(
            "No news channel configured. Ask an admin to run `/setup` first.", ephemeral=True
        )
        return

    articles = await bot.fetch_articles()
    new = [a for a in articles if a.get("article_id") not in bot.seen_ids]

    if not new:
        await interaction.followup.send("No new articles right now. Check back soon!", ephemeral=True)
        return

    count = 0
    for article in reversed(new[:MAX_PER_CYCLE]):
        bot.seen_ids.add(article.get("article_id", ""))
        try:
            await channel.send(embed=build_embed(article))
            count += 1
        except discord.HTTPException as exc:
            log.error("Send failed: %s", exc)

    await interaction.followup.send(f"📰 Posted **{count}** new article(s) to {channel.mention}.")


# ── /search ────────────────────────────────────────────────────────────────────
@bot.tree.command(name="search", description="Search Gulf & Saudi news by keyword.")
@app_commands.describe(query="Keyword to search for (e.g. NEOM, oil, Saudi Vision 2030)")
async def cmd_search(interaction: discord.Interaction, query: str):
    await interaction.response.defer(thinking=True)

    articles = await bot.fetch_articles(query=query, size=5)

    if not articles:
        await interaction.followup.send(f'No results found for **"{query}"**.', ephemeral=True)
        return

    embeds = [build_embed(a, color=discord.Color.orange()) for a in articles[:5]]
    await interaction.followup.send(
        content=f"🔍 Top results for **\"{query}\"**:",
        embeds=embeds,
    )


# ── /status ────────────────────────────────────────────────────────────────────
@bot.tree.command(name="status", description="Show bot status and stats.")
async def cmd_status(interaction: discord.Interaction):
    channel = bot.get_news_channel(interaction.guild)
    last = (
        f"<t:{int(bot.last_fetch.timestamp())}:R>" if bot.last_fetch else "Not yet"
    )

    embed = discord.Embed(title="Gulf News Bot — Status", color=discord.Color.blurple())
    embed.add_field(name="⚡ Auto Feed",    value="Running" if bot.auto_fetch.is_running() else "Stopped", inline=True)
    embed.add_field(name="🕐 Last Fetch",   value=last,                                                     inline=True)
    embed.add_field(name="📄 Seen Articles", value=str(len(bot.seen_ids)),                                  inline=True)
    embed.add_field(
        name="📺 News Channel",
        value=channel.mention if channel else "Not set — run `/setup`",
        inline=True,
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── /help ──────────────────────────────────────────────────────────────────────
@bot.tree.command(name="help", description="Show all available commands.")
async def cmd_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📰 Gulf News Bot — Commands",
        description="Breaking news from Gulf & Saudi Arabia, powered by newsdata.io",
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="⚙️ Setup (Admin only)",
        value=(
            "`/setup` — Register this channel as the news channel\n"
            "`/start` — Start the automatic news feed\n"
            "`/stop`  — Stop the automatic news feed"
        ),
        inline=False,
    )
    embed.add_field(
        name="📰 News",
        value=(
            "`/latest`         — Post the latest news right now\n"
            "`/search <query>` — Search news by keyword"
        ),
        inline=False,
    )
    embed.add_field(
        name="ℹ️ Info",
        value=(
            "`/status` — Show bot status\n"
            "`/help`   — Show this message"
        ),
        inline=False,
    )
    embed.set_footer(text="Auto-fetch runs every 15 minutes • Source: newsdata.io")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── Global command error handler ───────────────────────────────────────────────
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "You need **Administrator** permission to use this command."
    else:
        log.error("Slash command error: %s", error)
        msg = "Something went wrong. Please try again."

    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


# ── Entry point ────────────────────────────────────────────────────────────────
def main():
    if not TOKEN:
        raise ValueError("DISCORD_TOKEN is not set in .env")
    if not NEWS_API_KEY:
        raise ValueError("NEWS_API_KEY is not set in .env")

    bot.run(TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
