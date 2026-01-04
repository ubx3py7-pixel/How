# pip install playwright python-telegram-bot
# playwright install chromium

import asyncio
import random
import re
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# ───────────────── CONFIG ─────────────────
BOT_TOKEN = "8375060248:AAEOCPp8hU2lBYqDGt1SYwluQDQgqmDfWWA"
INSTA_SIGNUP = "https://www.instagram.com/accounts/emailsignup/"
HEADLESS = False  # ALWAYS FALSE (captcha / otp safe)

SCREENSHOTS = Path("ig_signup_shots")
SCREENSHOTS.mkdir(exist_ok=True)

EMAIL, NAME, PASSWORD, CONFIRM, OTP, USERNAME, FINAL = range(7)

# ───────────────── HUMAN BEHAVIOR ─────────────────
async def human_delay(a=0.4, b=1.4):
    await asyncio.sleep(random.uniform(a, b))

async def human_type(page, selector, text):
    await page.click(selector)
    for ch in text:
        await page.keyboard.type(ch)
        await asyncio.sleep(random.uniform(0.05, 0.18))

# ───────────────── UTILS ─────────────────
def rnd_birthday():
    return random.randint(1, 28), random.randint(1, 12), random.randint(1990, 2005)

async def snap(page, chat_id, ctx, tag):
    ts = datetime.now().strftime("%H%M%S")
    path = SCREENSHOTS / f"{chat_id}_{tag}_{ts}.png"
    await page.screenshot(path=path)
    await ctx.bot.send_photo(chat_id, photo=path, caption=tag)

# ───────────────── UI DETECTION ─────────────────
async def fill_dob_auto(page):
    d, m, y = rnd_birthday()

    selects = await page.query_selector_all("select")
    if len(selects) >= 3:
        try:
            await selects[0].select_option(str(m))
            await human_delay()
            await selects[1].select_option(str(d))
            await human_delay()
            await selects[2].select_option(str(y))
            return f"dropdown {d}/{m}/{y}"
        except:
            pass

    for name, val in {"day": d, "month": m, "year": y}.items():
        try:
            await human_type(page, f'input[name="{name}"]', str(val))
            await human_delay()
        except:
            pass

    return f"input {d}/{m}/{y}"

async def captcha_detected(page) -> bool:
    html = (await page.content()).lower()
    return any(k in html for k in [
        "captcha", "verify", "human", "challenge", "recaptcha", "hcaptcha"
    ])

async def otp_screen_detected(page) -> bool:
    selectors = [
        'input[autocomplete="one-time-code"]',
        'input[name*="confirmation"]',
        'text=/enter.*code/i',
    ]
    for s in selectors:
        try:
            if await page.query_selector(s):
                return True
        except:
            pass
    return False

# ───────────────── FLOW ─────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📧 Send email to start Instagram signup")
    return EMAIL

async def email_step(update, ctx):
    if "@" not in update.message.text:
        await update.message.reply_text("❌ Invalid email")
        return EMAIL
    ctx.user_data["email"] = update.message.text.strip()
    await update.message.reply_text("👤 Send full name")
    return NAME

async def name_step(update, ctx):
    ctx.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("🔑 Send password (min 6 chars)")
    return PASSWORD

async def password_step(update, ctx):
    if len(update.message.text) < 6:
        await update.message.reply_text("❌ Password too short")
        return PASSWORD

    ctx.user_data["password"] = update.message.text
    await update.message.reply_text("🚀 Launching browser…")

    asyncio.create_task(run_browser(ctx, update.effective_chat.id))
    return CONFIRM

async def run_browser(ctx, chat_id):
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=HEADLESS,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--disable-notifications",
        ]
    )

    page = await browser.new_page()
    await page.set_viewport_size({"width": 1280, "height": 900})

    ctx.user_data.update({
        "browser": browser,
        "page": page,
        "pw": pw,
        "pause": False,
    })

    await page.goto(INSTA_SIGNUP, timeout=60000)
    await human_delay(1.5, 2.5)
    await snap(page, chat_id, ctx, "opened")

    await ctx.bot.send_message(chat_id, "Page ready ✅\nReply **yes** to continue")

async def confirm_step(update, ctx):
    if update.message.text.lower() != "yes":
        await update.message.reply_text("Type **yes** to continue")
        return CONFIRM

    page = ctx.user_data["page"]

    await human_type(page, 'input[name="emailOrPhone"]', ctx.user_data["email"])
    await human_delay()
    await human_type(page, 'input[name="fullName"]', ctx.user_data["name"])
    await human_delay()

    dob_mode = await fill_dob_auto(page)
    await snap(page, update.effective_chat.id, ctx, "details_filled")

    await update.message.reply_text(
        f"🎂 DOB filled ({dob_mode})\nReply **yes** for password step"
    )
    return OTP

async def otp_step(update, ctx):
    page = ctx.user_data["page"]
    chat_id = update.effective_chat.id

    if update.message.text.lower() == "yes":
        await human_type(page, 'input[name="password"]', ctx.user_data["password"])
        await human_delay()

        if await captcha_detected(page):
            ctx.user_data["pause"] = True
            await ctx.bot.send_message(
                chat_id,
                "🛑 CAPTCHA detected\nSolve it manually in browser\nThen send /continue"
            )
            return OTP

        try:
            await page.get_by_role("button", name=re.compile("Next|Sign", re.I)).click()
        except:
            pass

        await human_delay(2, 3)

        if await otp_screen_detected(page):
            ctx.user_data["pause"] = True
            await ctx.bot.send_message(
                chat_id,
                "📩 OTP detected\nEnter OTP manually\nThen send /continue"
            )
            return OTP

        await update.message.reply_text("🆔 Send username or **yes** for random")
        return USERNAME

    await update.message.reply_text("Waiting… solve captcha/OTP if shown.")
    return OTP

async def continue_flow(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.user_data.get("pause"):
        await update.message.reply_text("Nothing to resume.")
        return

    ctx.user_data["pause"] = False
    await update.message.reply_text("▶️ Resuming… Send username or **yes**")
    return USERNAME

async def username_step(update, ctx):
    page = ctx.user_data["page"]
    username = update.message.text.strip()

    if username.lower() == "yes":
        username = f"user{random.randint(100000,999999)}"

    await human_type(page, 'input[name="username"]', username)
    await human_delay()
    await snap(page, update.effective_chat.id, ctx, "username")

    await update.message.reply_text("Final step → Reply **yes**")
    return FINAL

async def final_step(update, ctx):
    page = ctx.user_data["page"]

    if await captcha_detected(page):
        ctx.user_data["pause"] = True
        await update.message.reply_text(
            "🛑 CAPTCHA again\nSolve manually\nThen send /continue"
        )
        return FINAL

    try:
        await page.get_by_role("button", name=re.compile("Next|Create", re.I)).click()
    except:
        pass

    await human_delay(3, 4)
    await snap(page, update.effective_chat.id, ctx, "done")

    await ctx.user_data["browser"].close()
    await ctx.user_data["pw"].stop()
    ctx.user_data.clear()

    await update.message.reply_text("🎉 Signup flow finished.")
    return ConversationHandler.END

async def cancel(update, ctx):
    try:
        if ctx.user_data.get("browser"):
            await ctx.user_data["browser"].close()
        if ctx.user_data.get("pw"):
            await ctx.user_data["pw"].stop()
    except:
        pass

    ctx.user_data.clear()
    await update.message.reply_text("❌ Cancelled")
    return ConversationHandler.END

# ───────────────── MAIN ─────────────────
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            EMAIL: [MessageHandler(filters.TEXT, email_step)],
            NAME: [MessageHandler(filters.TEXT, name_step)],
            PASSWORD: [MessageHandler(filters.TEXT, password_step)],
            CONFIRM: [MessageHandler(filters.TEXT, confirm_step)],
            OTP: [MessageHandler(filters.TEXT, otp_step)],
            USERNAME: [MessageHandler(filters.TEXT, username_step)],
            FINAL: [MessageHandler(filters.TEXT, final_step)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("continue", continue_flow))

    print("🤖 Bot running")
    app.run_polling()

if __name__ == "__main__":
    main()
