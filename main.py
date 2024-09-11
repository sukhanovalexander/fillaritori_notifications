#!/usr/bin/env python
# pylint: disable=unused-argument
# This program is dedicated to the public domain under the CC0 license.

"""
Simple Bot to reply to Telegram messages.

First, a few handler functions are defined. Then, those functions are passed to
the Application and registered at their respective places.
Then, the bot is started and runs until we press Ctrl-C on the command line.

Usage:
Basic Echobot example, repeats messages.
Press Ctrl-C on the command line or send a signal to the process to stop the
bot.
"""
import asyncio
import re
import requests
import sqlite3
from db_handle import init_db, add_search, delete_search, list_searches, fetch_all_searches, update_search
from lxml import html
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler
import schedule
import time
import logging
from config import valid_url_list
from telegram import ForceReply, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

TOKEN = "7194463974:AAFHsByUOUbMaKGGMgy15trdspR0KPY9qsg"

# Define a few command handlers. These usually take the two arguments update and
# context.
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    chat_id = update.effective_chat.id
    with sqlite3.connect('bot_data.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''INSERT OR IGNORE INTO user_data (chat_id) VALUES (?)''', (chat_id,))
        conn.commit()
    await update.message.reply_text('Welcome! Use /add_search to create a new search.')


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    await update.message.reply_text("Valid commands: /add_search\n/list_searches\n/delete_search\n/help\n")


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Echo the user message."""
    await update.message.reply_text(update.message.text)


async def alarm(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the alarm message."""
    bot = Bot(token=TOKEN)
    url = 'https://www.fillaritori.com/forum/13-kiekot/'
    response = requests.get(url)

    if response.status_code == 200:
        tree = html.fromstring(response.content)

        items = tree.xpath('//div[@data-tableid="topics"]/ol/li[2]/div[@class="ipsDataItem_main"]/h4/span[2]/a/@href')
        await bot.send_message(chat_id=91914942, text=items[0])


async def add_search_command(update: Update, context):
    chat_id = update.effective_chat.id
    args = context.args

    if len(args) < 3:
        await update.message.reply_text(
            f"Usage: /add_search <url> <keyword> <max_price>\n")
        return

    url, keyword, max_price = args[0], args[1], args[2]

    try:
        max_price = int(max_price)
    except ValueError:
        await update.message.reply_text("Invalid max price. Please enter a number.")
        return

    try:
        if url not in valid_url_list:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Invalid url")
        return
    # find current 2nd ad
    last_match = get_last_match(url)

    # Add the search to the database
    add_search(chat_id, url, keyword, max_price, last_match)
    await update.message.reply_text(f"Search added for {url}: '{keyword}' with max price {max_price}.")


# Command to list all searches for the user
async def list_searches_command(update: Update, context):
    chat_id = update.effective_chat.id
    searches = list_searches(chat_id)

    if not searches:
        await update.message.reply_text("You have no saved searches.")
        return

    message = "Your saved searches:\n"
    for search in searches:
        search_id, url, keyword, max_price = search
        message += f"ID: {search_id} | url: {url} | Keyword: {keyword} | Max Price: {max_price}\n"

    await update.message.reply_text(message)


async def delete_search_command(update: Update, context):
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        await update.message.reply_text("Usage: /delete_search <search_id>")
        return

    search_id = args[0]

    try:
        search_id = int(search_id)
    except ValueError:
        await update.message.reply_text("Invalid search ID. Please enter a number.")
        return

    # Delete the search
    delete_search(chat_id, search_id)
    await update.message.reply_text(f"Search with ID {search_id} has been deleted(or never was present).")


def get_last_match(url):
    response = requests.get(url)
    tree = html.fromstring(response.content)
    item = tree.xpath('//div[@data-tableid="topics"]/ol/li[2]/div[@class="ipsDataItem_main"]/h4/span[2]/a/span')[0]
    return item.text.strip()


async def run_checks_for_all_users(context: ContextTypes.DEFAULT_TYPE):
    searches = fetch_all_searches()
    logger.info("Fetched searches")
    bot = Bot(token=TOKEN)
    for search in searches:
        search_id, chat_id, url, keyword, max_price, last_match = search
        logger.info(f"Checking {search_id} search for new ads")
        await check_new_ads_for_search(bot, search_id, chat_id, url, keyword, max_price, last_match)


async def get_price_from_request(response):
    tree = html.fromstring(response.content)
    data = tree.xpath("//strong[contains(text(), 'Price') or contains(text(), 'Hinta')]/following-sibling::text()")
    raw = data[0] if len(data) else '0'
    value = re.sub(r'\D', '', raw)
    return int(value) if value else 0


async def get_text_from_request(response):
    tree = html.fromstring(response.content)
    listing_text_fields = tree.xpath("//div[@data-role='commentContent'][1]//text()")
    return ' '.join([text.strip() for text in listing_text_fields if text.strip()])


async def check_new_ads_for_search(bot, search_id, chat_id, url, keyword, max_price, last_match):
    response = requests.get(f'{url}')
    price = 0
    listing_content = ''
    tree = html.fromstring(response.content)
    items = tree.xpath('//div[@data-tableid="topics"]/ol/li/div[@class="ipsDataItem_main"]/h4/span[2]/a/span')
    first_listing = items[0].text.strip()
    for num, element in enumerate(items):
        logger.info(f"Checking {num+1} listing on page")
        if element.text.strip() == last_match:
            logger.info("Met last known listing")
            update_search(search_id, first_listing)
            break
        listing_url = tree.xpath(f'//div[@data-tableid="topics"]/ol/li[{num + 1}]/div[@class="ipsDataItem_main"]/h4'
                                 f'/span[2]/a/@href')[0]
        listing_response = requests.get(listing_url)
        if listing_response.status_code == 200:
            logger.info(f"Checking {num + 1} listing price")
            price = await get_price_from_request(listing_response)
            listing_content = await get_text_from_request(listing_response)
        if keyword.lower() in listing_content.lower() and (price <= max_price or max_price == 0):
            await bot.send_message(chat_id=chat_id, text=listing_url)


def main() -> None:
    """Start the bot."""
    # Initialize the database
    init_db()

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(TOKEN).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add_search", add_search_command))
    application.add_handler(CommandHandler("list_searches", list_searches_command))
    application.add_handler(CommandHandler("delete_search", delete_search_command))
    application.add_handler(CommandHandler("help", help_command))
    application.job_queue.run_repeating(run_checks_for_all_users, 10*60)

    # application.job_queue.run_repeating(run_checks_for_all_users, 5)
    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
