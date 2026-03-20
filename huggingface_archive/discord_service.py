"""
Discord Service — bot commands and message handling.
Provides the Discord-based interface for Jarvis.
Includes a surgical DNS bypass for restricted environments.
"""
import logging
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import io
import aiohttp
import socket
import dns.resolver

from services import memory_service, rag_service, personality_service, llm_service
import config

logger = logging.getLogger(__name__)

# --- DNS Bypass ---

class CustomResolver(aiohttp.resolver.AbstractResolver):
    """Bypasses platform DNS by asking Google (8.8.8.8) directly."""
    def __init__(self):
        self.dns_resolver = dns.resolver.Resolver()
        self.dns_resolver.nameservers = ['8.8.8.8', '8.8.4.4', '1.1.1.1']

    async def resolve(self, host, port=0, family=socket.AF_INET):
        logger.info(f"[DNS Bypass] Resolving {host}...")
        try:
            # Manually resolve via Google DNS
            answers = self.dns_resolver.resolve(host, 'A')
            ips = [str(rdata) for rdata in answers]
            logger.info(f"[DNS Bypass] {host} -> {ips}")
            return [{"hostname": host, "host": ip, "port": port, "family": family, "proto": 0, "flags": 0} for ip in ips]
        except Exception as e:
            logger.error(f"[DNS Bypass] Resolution failed for {host}: {e}")
            # Fallback to system resolver just in case
            return [{"hostname": host, "host": host, "port": port, "family": family, "proto": 0, "flags": 0}]

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True 
intents.members = True

class JarvisBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.custom_session = None

    async def setup_hook(self):
        # Create a session with our custom resolver
        connector = aiohttp.TCPConnector(
            resolver=CustomResolver(),
            family=socket.AF_INET,
            trust_env=False # Ignore platform proxies that break connections
        )
        self.http.connector = connector
        
        # Sync slash commands
        await self.tree.sync()
        logger.info("Discord slash commands synced.")

    async def on_ready(self):
        logger.info("========================================")
        logger.info(f"JARVIS LOGGED IN AS {self.user} (ID: {self.user.id})")
        logger.info("========================================")

bot = JarvisBot()

# --- Slash Commands ---

@bot.tree.command(name="hello", description="Say hi to Jarvis!")
async def hello(interaction: discord.Interaction):
    user = interaction.user
    memory_service.upsert_user(user.id, user.name, user.display_name)
    await interaction.response.send_message(
        f"Hey {user.display_name}! 👋 I'm Jarvis, your personal AI companion.\n\n"
        f"I'm now running on Discord for a more stable experience!\n"
        f"Try these commands:\n"
        f"** /log ** — Tell me about your day\n"
        f"** /goal ** — Set a new goal\n"
        f"** /plan ** — Get today's game plan\n"
        f"** /review ** — End-of-day reflection\n"
        f"** /streak ** — Check your streak 🔥\n\n"
        f"You can also attach a PDF journal, and I'll remember it all. 💪"
    )

@bot.tree.command(name="log", description="Log your progress or update your day.")
@app_commands.describe(text="What's on your mind?")
async def log(interaction: discord.Interaction, text: str):
    user_id = interaction.user.id
    memory_service.save_log(user_id, text)
    today = datetime.now().strftime("%Y-%m-%d")
    await rag_service.add_log_to_rag(user_id, text, today)
    streak = memory_service.get_streak(user_id)
    await interaction.response.send_message(
        f"Logged! ✅\n🔥 **Streak:** {streak['current_streak']} days\n\nKeep it rolling."
    )

@bot.tree.command(name="goal", description="Set or view your goals.")
@app_commands.describe(title="New goal title (optional)")
async def goal(interaction: discord.Interaction, title: str = None):
    user_id = interaction.user.id
    if not title:
        goals = memory_service.get_active_goals(user_id)
        if not goals:
            await interaction.response.send_message("No active goals yet. Use `/goal title:Your Goal` to set one!")
            return
        msg = "🎯 **Your Goals:**\n\n"
        for i, g in enumerate(goals, 1):
            msg += f"{i}. {g['title']}\n"
        await interaction.response.send_message(msg)
        return
    memory_service.save_goal(user_id, title)
    await interaction.response.send_message(f"Goal set: **{title}** 🎯\n\nLet's make it happen.")

@bot.tree.command(name="plan", description="Generate today's game plan.")
async def plan(interaction: discord.Interaction):
    await interaction.response.defer()
    user_id = interaction.user.id
    plan_text = await generate_plan_internal(user_id)
    await interaction.followup.send(plan_text)

@bot.tree.command(name="review", description="End-of-day reflection and review.")
async def review(interaction: discord.Interaction):
    await interaction.response.defer()
    user_id = interaction.user.id
    review_text = await generate_review_internal(user_id)
    await interaction.followup.send(review_text)

@bot.tree.command(name="streak", description="Check your current streaks.")
async def streak(interaction: discord.Interaction):
    user_id = interaction.user.id
    streak_data = memory_service.get_streak(user_id)
    await interaction.response.send_message(
        f"🔥 **Streak Stats**\n\n"
        f"• Current streak: {streak_data['current_streak']} days\n"
        f"• Longest streak: {streak_data['longest_streak']} days\n"
        f"• Total logs: {streak_data['total_logs']}\n\n"
        f"{'Keep going! 💪' if streak_data['current_streak'] > 0 else 'Start a new streak today with /log!'}"
    )

# --- Message Handling (Chat + PDFs) ---

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if message.attachments:
        for attachment in message.attachments:
            if attachment.filename.lower().endswith(".pdf"):
                await process_pdf(message, attachment)
                return
    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mentioned = bot.user in message.mentions
    if is_dm or is_mentioned:
        clean_content = message.content.replace(f'<@!{bot.user.id}>', '').replace(f'<@{bot.user.id}>', '').strip()
        if not clean_content and is_mentioned:
            await message.reply("Yes? 🐾 Use commands or just chat with me!")
            return
        async with message.channel.typing():
            response = await chat_response(message.author.id, clean_content)
            await message.reply(response)
    await bot.process_commands(message)

# --- Service Internals ---

async def process_pdf(message, attachment):
    await message.reply("Got it! Processing your PDF... 📄")
    async with aiohttp.ClientSession() as session:
        async with session.get(attachment.url) as resp:
            if resp.status != 200:
                await message.reply("Failed to download the PDF.")
                return
            content = await resp.read()
    chunk_count = await rag_service.ingest_pdf(message.author.id, content)
    await message.reply(
        f"Done! Processed **{chunk_count}** chunks from your PDF. "
        f"I'll use this to understand you better. 🧠"
    )

async def chat_response(user_id: int, text: str) -> str:
    rag_chunks = await rag_service.query(user_id, text, k=3)
    rag_context = "\n".join(rag_chunks) if rag_chunks else ""
    personality_context = await personality_service.build_context(user_id)
    full_context = ""
    if personality_context:
        full_context += personality_context + "\n\n"
    if rag_context:
        full_context += f"## Relevant Memories\n{rag_context}"
    try:
        return await llm_service.generate(text, context=full_context)
    except Exception as e:
        logger.error(f"Error generating response: {e}")
        return "Hmm, something went wrong on my end. Try again in a sec! 🐾"

async def generate_plan_internal(user_id: int) -> str:
    personality_context = await personality_service.build_context(user_id)
    rag_chunks = await rag_service.query(user_id, "daily priorities and tasks", k=3)
    rag_context = "\n".join(rag_chunks) if rag_chunks else ""
    context = personality_context
    if rag_context:
        context += f"\n\n## Relevant Memories\n{rag_context}"
    prompt = """Generate a morning plan for today. Include:
1. 3 priority tasks (realistic, focused)
2. One thing to avoid today (based on their patterns)
3. A short motivational line

Keep it SHORT. No fluff. Golden retriever energy."""
    return await llm_service.generate(prompt, context=context)

async def generate_review_internal(user_id: int) -> str:
    today_logs = memory_service.get_today_logs(user_id)
    personality_context = await personality_service.build_context(user_id)
    log_text = "\n".join([l["content"] for l in today_logs]) if today_logs else "No logs today."
    context = personality_context + f"\n\n## Today's Logs\n{log_text}"
    prompt = """Generate a brief end-of-day review. Include:
1. What was accomplished (based on logs)
2. Any blockers noticed
3. One suggestion for tomorrow
4. Score the day out of 10

If no logs were made, gently remind them to log.
Keep it short and encouraging. Golden retriever energy."""
    return await llm_service.generate(prompt, context=context)

async def send_proactive_message(user_id: int, text: str):
    user = await bot.fetch_user(user_id)
    if user:
        await user.send(text)
