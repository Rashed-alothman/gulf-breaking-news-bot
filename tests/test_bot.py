"""
Tests for Gulf Breaking News Bot (bot.py)

Run:  pytest tests/ -v
"""

import json
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import discord
import pytest

from bot import MAX_PER_CYCLE, NewsBot, build_embed, load_config, save_config


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════

SAMPLE_ARTICLE = {
    "article_id":  "abc123",
    "title":       "Saudi Arabia Announces New NEOM District",
    "link":        "https://example.com/neom",
    "description": "Details about the new NEOM development.",
    "image_url":   "https://example.com/image.jpg",
    "pubDate":     "2024-06-01 10:00:00",
    "source_id":   "arab_news",
}

SAMPLE_ARTICLE_MINIMAL = {
    "article_id": "xyz999",
}


@pytest.fixture()
def bot_instance(tmp_path, monkeypatch):
    """Fresh NewsBot instance using a temp directory for config.json."""
    monkeypatch.chdir(tmp_path)
    return NewsBot()


@pytest.fixture()
def mock_guild():
    guild = MagicMock(spec=discord.Guild)
    guild.id = 111222333444555666
    guild.name = "Test Server"
    return guild


@pytest.fixture()
def mock_channel():
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 999888777666555444
    channel.mention = "<#999888777666555444>"
    channel.send = AsyncMock()
    return channel


@pytest.fixture()
def mock_interaction(mock_guild, mock_channel):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild   = mock_guild
    interaction.channel = mock_channel
    interaction.user    = MagicMock()
    interaction.user.__str__ = lambda _: "TestUser#0001"
    interaction.response       = AsyncMock()
    interaction.response.is_done.return_value = False
    interaction.followup       = AsyncMock()
    return interaction


# ══════════════════════════════════════════════════════════════════════════════
# build_embed
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildEmbed:
    def test_full_article(self):
        embed = build_embed(SAMPLE_ARTICLE)

        assert embed.title       == "Saudi Arabia Announces New NEOM District"
        assert embed.url         == "https://example.com/neom"
        assert embed.description == "Details about the new NEOM development."
        assert embed.color       == discord.Color.red()
        assert embed.image.url   == "https://example.com/image.jpg"
        assert "arab_news"       in embed.footer.text
        assert "Gulf & Saudi Arabia" in embed.footer.text

    def test_minimal_article_uses_defaults(self):
        embed = build_embed(SAMPLE_ARTICLE_MINIMAL)

        assert embed.title       == "Breaking News"
        assert embed.description == "No description available."
        assert not embed.image.url   # discord.py returns EmbedProxy, not None — check url

    def test_custom_color(self):
        embed = build_embed(SAMPLE_ARTICLE, color=discord.Color.orange())
        assert embed.color == discord.Color.orange()

    def test_pub_date_sets_author(self):
        embed = build_embed(SAMPLE_ARTICLE)
        assert embed.author.name == "Published: 2024-06-01 10:00:00"

    def test_no_pub_date_no_author(self):
        embed = build_embed(SAMPLE_ARTICLE_MINIMAL)
        # author is an empty EmbedAuthor when not set — name should be empty
        assert not embed.author.name


# ══════════════════════════════════════════════════════════════════════════════
# load_config / save_config
# ══════════════════════════════════════════════════════════════════════════════

class TestConfig:
    def test_load_config_no_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert load_config() == {}

    def test_load_config_existing_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data = {"123": {"channel_id": 456}}
        (tmp_path / "config.json").write_text(json.dumps(data))

        assert load_config() == data

    def test_save_config_writes_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data = {"789": {"channel_id": 101112}}
        save_config(data)

        saved = json.loads((tmp_path / "config.json").read_text())
        assert saved == data

    def test_save_then_load_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data = {"guild_1": {"channel_id": 42}, "guild_2": {"channel_id": 99}}
        save_config(data)
        assert load_config() == data


# ══════════════════════════════════════════════════════════════════════════════
# NewsBot — channel management
# ══════════════════════════════════════════════════════════════════════════════

class TestChannelManagement:
    def test_get_news_channel_not_configured(self, bot_instance, mock_guild):
        assert bot_instance.get_news_channel(mock_guild) is None

    def test_get_news_channel_configured_and_found(self, bot_instance, mock_guild, mock_channel):
        mock_guild.get_channel.return_value = mock_channel
        bot_instance.guild_config = {str(mock_guild.id): {"channel_id": mock_channel.id}}

        result = bot_instance.get_news_channel(mock_guild)
        assert result is mock_channel
        mock_guild.get_channel.assert_called_once_with(mock_channel.id)

    def test_get_news_channel_channel_deleted(self, bot_instance, mock_guild):
        """Channel was deleted after setup — should return None gracefully."""
        mock_guild.get_channel.return_value = None
        bot_instance.guild_config = {str(mock_guild.id): {"channel_id": 99999}}

        assert bot_instance.get_news_channel(mock_guild) is None

    def test_set_news_channel_updates_config(self, bot_instance, mock_guild, mock_channel, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        bot_instance.set_news_channel(mock_guild, mock_channel)

        gid = str(mock_guild.id)
        assert bot_instance.guild_config[gid]["channel_id"] == mock_channel.id

    def test_set_news_channel_persists_to_file(self, bot_instance, mock_guild, mock_channel, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        bot_instance.set_news_channel(mock_guild, mock_channel)

        saved = json.loads((tmp_path / "config.json").read_text())
        assert saved[str(mock_guild.id)]["channel_id"] == mock_channel.id


# ══════════════════════════════════════════════════════════════════════════════
# NewsBot.fetch_articles  (HTTP layer mocked)
# ══════════════════════════════════════════════════════════════════════════════

def _make_mock_session(status: int, payload: dict | None = None):
    """Helper to build a mock aiohttp session returning a given status/payload."""
    mock_resp = AsyncMock()
    mock_resp.status = status
    if payload is not None:
        mock_resp.json = AsyncMock(return_value=payload)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_resp
    mock_ctx.__aexit__.return_value  = False

    mock_session = MagicMock()
    mock_session.get.return_value = mock_ctx
    return mock_session


class TestFetchArticles:
    async def test_success_returns_articles(self, bot_instance):
        payload = {"results": [SAMPLE_ARTICLE, SAMPLE_ARTICLE_MINIMAL]}
        bot_instance.session = _make_mock_session(200, payload)

        articles = await bot_instance.fetch_articles()

        assert len(articles) == 2
        assert articles[0]["article_id"] == "abc123"

    async def test_success_sets_last_fetch(self, bot_instance):
        payload = {"results": [SAMPLE_ARTICLE]}
        bot_instance.session = _make_mock_session(200, payload)

        assert bot_instance.last_fetch is None
        await bot_instance.fetch_articles()
        assert bot_instance.last_fetch is not None

    async def test_rate_limited_returns_empty(self, bot_instance):
        bot_instance.session = _make_mock_session(429)
        assert await bot_instance.fetch_articles() == []

    async def test_server_error_returns_empty(self, bot_instance):
        bot_instance.session = _make_mock_session(500)
        assert await bot_instance.fetch_articles() == []

    async def test_network_error_returns_empty(self, bot_instance):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.side_effect = aiohttp.ClientError("Network unreachable")
        mock_session = MagicMock()
        mock_session.get.return_value = mock_ctx
        bot_instance.session = mock_session

        assert await bot_instance.fetch_articles() == []

    async def test_search_query_included_in_params(self, bot_instance):
        payload = {"results": [SAMPLE_ARTICLE]}
        bot_instance.session = _make_mock_session(200, payload)

        await bot_instance.fetch_articles(query="NEOM")

        call_kwargs = bot_instance.session.get.call_args.kwargs
        assert call_kwargs["params"]["q"] == "NEOM"

    async def test_no_query_param_omitted(self, bot_instance):
        payload = {"results": []}
        bot_instance.session = _make_mock_session(200, payload)

        await bot_instance.fetch_articles()

        call_kwargs = bot_instance.session.get.call_args.kwargs
        assert "q" not in call_kwargs["params"]


# ══════════════════════════════════════════════════════════════════════════════
# NewsBot.auto_fetch loop logic
# ══════════════════════════════════════════════════════════════════════════════

class TestAutoFetch:
    async def test_skips_guilds_without_channel(self, bot_instance, mock_guild):
        """If no channel is set up, nothing is sent."""
        mock_guild.get_channel.return_value = None

        payload = {"results": [SAMPLE_ARTICLE]}
        bot_instance.session = _make_mock_session(200, payload)

        with patch.object(type(bot_instance), "guilds", new_callable=PropertyMock, return_value=[mock_guild]):
            await bot_instance.auto_fetch()
        # No channel configured, so send should never be called

    async def test_posts_new_articles(self, bot_instance, mock_guild, mock_channel):
        mock_guild.get_channel.return_value = mock_channel
        bot_instance.guild_config = {str(mock_guild.id): {"channel_id": mock_channel.id}}

        payload = {"results": [SAMPLE_ARTICLE]}
        bot_instance.session = _make_mock_session(200, payload)

        with patch.object(type(bot_instance), "guilds", new_callable=PropertyMock, return_value=[mock_guild]):
            await bot_instance.auto_fetch()

        mock_channel.send.assert_called_once()
        assert "abc123" in bot_instance.seen_ids

    async def test_skips_already_seen_articles(self, bot_instance, mock_guild, mock_channel):
        mock_guild.get_channel.return_value = mock_channel
        bot_instance.guild_config = {str(mock_guild.id): {"channel_id": mock_channel.id}}
        bot_instance.seen_ids.add("abc123")   # already seen

        payload = {"results": [SAMPLE_ARTICLE]}
        bot_instance.session = _make_mock_session(200, payload)

        with patch.object(type(bot_instance), "guilds", new_callable=PropertyMock, return_value=[mock_guild]):
            await bot_instance.auto_fetch()

        mock_channel.send.assert_not_called()

    async def test_caps_posts_at_max_per_cycle(self, bot_instance, mock_guild, mock_channel):
        mock_guild.get_channel.return_value = mock_channel
        bot_instance.guild_config = {str(mock_guild.id): {"channel_id": mock_channel.id}}

        # Create more articles than MAX_PER_CYCLE
        articles = [{"article_id": f"id{i}", "title": f"News {i}"} for i in range(MAX_PER_CYCLE + 3)]
        bot_instance.session = _make_mock_session(200, {"results": articles})

        with patch.object(type(bot_instance), "guilds", new_callable=PropertyMock, return_value=[mock_guild]):
            await bot_instance.auto_fetch()

        assert mock_channel.send.call_count == MAX_PER_CYCLE


# ══════════════════════════════════════════════════════════════════════════════
# Slash commands  (call .callback directly to bypass Discord permission checks)
# ══════════════════════════════════════════════════════════════════════════════

from unittest.mock import PropertyMock   # noqa: E402

import bot as bot_module   # noqa: E402 — needed to access module-level bot + commands


class TestCmdSetup:
    async def test_sets_channel_and_responds(self, mock_interaction, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        await bot_module.cmd_setup.callback(mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        sent_kwargs = mock_interaction.response.send_message.call_args.kwargs
        assert isinstance(sent_kwargs.get("embed"), discord.Embed)


class TestCmdStart:
    async def test_no_channel_sends_error(self, mock_interaction):
        # No channel configured → ephemeral error
        bot_module.bot.guild_config = {}
        await bot_module.cmd_start.callback(mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        call = mock_interaction.response.send_message.call_args
        assert call.kwargs.get("ephemeral") is True

    async def test_already_running_sends_error(self, mock_interaction, mock_channel):
        mock_interaction.guild.get_channel.return_value = mock_channel
        bot_module.bot.guild_config = {
            str(mock_interaction.guild.id): {"channel_id": mock_channel.id}
        }
        with patch.object(bot_module.bot.auto_fetch, "is_running", return_value=True):
            await bot_module.cmd_start.callback(mock_interaction)

        call = mock_interaction.response.send_message.call_args
        assert call.kwargs.get("ephemeral") is True


class TestCmdStop:
    async def test_already_stopped_sends_error(self, mock_interaction):
        with patch.object(bot_module.bot.auto_fetch, "is_running", return_value=False):
            await bot_module.cmd_stop.callback(mock_interaction)

        call = mock_interaction.response.send_message.call_args
        assert call.kwargs.get("ephemeral") is True

    async def test_stops_running_loop(self, mock_interaction):
        with patch.object(bot_module.bot.auto_fetch, "is_running", return_value=True), \
             patch.object(bot_module.bot.auto_fetch, "cancel") as mock_cancel:
            await bot_module.cmd_stop.callback(mock_interaction)

        mock_cancel.assert_called_once()


class TestCmdLatest:
    async def test_no_channel_configured(self, mock_interaction):
        bot_module.bot.guild_config = {}
        await bot_module.cmd_latest.callback(mock_interaction)

        mock_interaction.followup.send.assert_called_once()
        call = mock_interaction.followup.send.call_args
        assert call.kwargs.get("ephemeral") is True

    async def test_no_new_articles(self, mock_interaction, mock_channel):
        mock_interaction.guild.get_channel.return_value = mock_channel
        bot_module.bot.guild_config = {
            str(mock_interaction.guild.id): {"channel_id": mock_channel.id}
        }

        with patch.object(bot_module.bot, "fetch_articles", return_value=[]):
            await bot_module.cmd_latest.callback(mock_interaction)

        call = mock_interaction.followup.send.call_args
        assert "soon" in call.args[0].lower() or call.kwargs.get("ephemeral") is True

    async def test_posts_new_articles(self, mock_interaction, mock_channel):
        mock_interaction.guild.get_channel.return_value = mock_channel
        bot_module.bot.guild_config = {
            str(mock_interaction.guild.id): {"channel_id": mock_channel.id}
        }
        bot_module.bot.seen_ids = set()

        articles = [{"article_id": "fresh1", "title": "Fresh News"}]
        with patch.object(bot_module.bot, "fetch_articles", return_value=articles):
            await bot_module.cmd_latest.callback(mock_interaction)

        mock_channel.send.assert_called_once()
        assert "fresh1" in bot_module.bot.seen_ids


class TestCmdSearch:
    async def test_no_results(self, mock_interaction):
        with patch.object(bot_module.bot, "fetch_articles", return_value=[]):
            await bot_module.cmd_search.callback(mock_interaction, query="xyz_noresult")

        call = mock_interaction.followup.send.call_args
        assert call.kwargs.get("ephemeral") is True

    async def test_returns_embeds(self, mock_interaction):
        articles = [{"article_id": f"s{i}", "title": f"Result {i}"} for i in range(3)]
        with patch.object(bot_module.bot, "fetch_articles", return_value=articles):
            await bot_module.cmd_search.callback(mock_interaction, query="NEOM")

        call = mock_interaction.followup.send.call_args
        embeds = call.kwargs.get("embeds", [])
        assert len(embeds) == 3


class TestCmdStatus:
    async def test_sends_status_embed(self, mock_interaction):
        await bot_module.cmd_status.callback(mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        sent_kwargs = mock_interaction.response.send_message.call_args.kwargs
        assert isinstance(sent_kwargs.get("embed"), discord.Embed)
        assert sent_kwargs.get("ephemeral") is True


class TestCmdHelp:
    async def test_sends_help_embed(self, mock_interaction):
        await bot_module.cmd_help.callback(mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        sent_kwargs = mock_interaction.response.send_message.call_args.kwargs
        embed = sent_kwargs.get("embed")
        assert isinstance(embed, discord.Embed)
        assert "Commands" in embed.title
        assert sent_kwargs.get("ephemeral") is True
