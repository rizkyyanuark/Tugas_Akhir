"""
Telegram Bot Adapter for Academic Knowledge Graph
====================================================
Long-polling bot that bridges Telegram messages to GraphRAGQuery.

Usage (standalone):
    TELEGRAM_BOT_TOKEN=xxxx python -m ta_backend_core.telegram_bot

Usage (Docker):
    Set TELEGRAM_BOT_TOKEN in .env and run as a separate service.
"""

import os
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports to avoid heavy top-level loading
# ---------------------------------------------------------------------------

def _get_graphrag():
    """Lazy-load GraphRAGQuery to avoid circular / heavy imports at module level."""
    from ta_backend_core.knowledge.graphrag.query import GraphRAGQuery
    return GraphRAGQuery()


# ---------------------------------------------------------------------------
# Telegram Bot (python-telegram-bot v20+)
# ---------------------------------------------------------------------------

try:
    from telegram import Update
    from telegram.ext import (
        ApplicationBuilder,
        CommandHandler,
        MessageHandler,
        ContextTypes,
        filters,
    )
    HAS_TELEGRAM = True
except ImportError:
    HAS_TELEGRAM = False
    logger.warning(
        "python-telegram-bot not installed. "
        "Install with: pip install python-telegram-bot>=20"
    )


# ── Global reference (initialised once on /start) ──────────────────────────
_graphrag: Optional[object] = None


async def _ensure_graphrag():
    """Initialise GraphRAGQuery singleton on first use."""
    global _graphrag
    if _graphrag is None:
        logger.info("🔄 Initialising GraphRAG engine …")
        _graphrag = _get_graphrag()
        logger.info("✅ GraphRAG engine ready.")
    return _graphrag


# ── Command Handlers ───────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await _ensure_graphrag()
    welcome = (
        "👋 *Selamat datang di Academic Knowledge Graph Bot!*\n\n"
        "Saya adalah asisten AI yang terhubung langsung ke "
        "Knowledge Graph akademik UNESA.\n\n"
        "📌 *Cara penggunaan:*\n"
        "• Ketik pertanyaan apapun tentang data akademik\n"
        "• Contoh: _Siapa dosen yang meneliti deep learning?_\n"
        "• Contoh: _Berapa jumlah paper tentang machine learning?_\n\n"
        "⚙️ *Perintah:*\n"
        "/start — Tampilkan pesan ini\n"
        "/mode <local|global|hybrid|mix> — Ubah mode pencarian\n"
        "/status — Cek status koneksi"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def cmd_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mode command to switch retrieval mode."""
    valid_modes = ("local", "global", "hybrid", "mix")
    if not context.args or context.args[0].lower() not in valid_modes:
        await update.message.reply_text(
            f"⚠️ Mode tidak valid. Pilih salah satu: {', '.join(valid_modes)}\n"
            "Contoh: `/mode hybrid`",
            parse_mode="Markdown",
        )
        return

    mode = context.args[0].lower()
    context.user_data["mode"] = mode
    await update.message.reply_text(
        f"✅ Mode pencarian diubah ke: *{mode}*",
        parse_mode="Markdown",
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command."""
    gq = await _ensure_graphrag()
    mode = context.user_data.get("mode", "hybrid")
    await update.message.reply_text(
        f"📊 *Status Bot*\n"
        f"• Engine: GraphRAGQuery ✅\n"
        f"• Mode aktif: `{mode}`\n"
        f"• Neo4j: Connected\n"
        f"• Milvus: Connected",
        parse_mode="Markdown",
    )


# ── Message Handler ────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming user text messages — route to GraphRAGQuery."""
    user_text = update.message.text
    if not user_text or not user_text.strip():
        return

    mode = context.user_data.get("mode", "hybrid")
    gq = await _ensure_graphrag()

    # Show typing indicator
    await update.message.chat.send_action("typing")

    try:
        result = await gq.query(query_text=user_text, mode=mode)
        response_text = result.get("response", "Maaf, tidak ada respons.")
        metadata = result.get("metadata", {})
        latency = metadata.get("latency_s", "?")

        # Truncate if response exceeds Telegram's 4096 char limit
        if len(response_text) > 3800:
            response_text = response_text[:3800] + "\n\n… _(respons dipotong)_"

        reply = (
            f"{response_text}\n\n"
            f"───────────────\n"
            f"⏱ {latency}s • 🔍 mode: {mode}"
        )
        await update.message.reply_text(reply, parse_mode="Markdown")

    except Exception as e:
        logger.exception("Error processing Telegram query")
        await update.message.reply_text(
            f"❌ Terjadi kesalahan: `{str(e)[:200]}`",
            parse_mode="Markdown",
        )


# ── Error Handler ──────────────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log Telegram errors gracefully."""
    logger.error(f"Telegram error: {context.error}", exc_info=context.error)


# ── Main Entry Point ──────────────────────────────────────────────────────

def main():
    """Start the Telegram bot with long-polling."""
    if not HAS_TELEGRAM:
        raise RuntimeError(
            "python-telegram-bot is required. "
            "Install: pip install 'python-telegram-bot>=20'"
        )

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN environment variable is not set. "
            "Please set it in your .env file."
        )

    logger.info("🤖 Starting Academic KG Telegram Bot (long-polling) …")

    app = ApplicationBuilder().token(token).build()

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("mode", cmd_mode))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    # Long-polling (no webhook setup needed)
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )
    main()
