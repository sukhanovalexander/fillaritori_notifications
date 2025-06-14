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
import pickle
from db_handle import (init_db, add_search, delete_search, list_searches, fetch_all_searches, update_search,
                       get_stored_request, create_stored_request, update_stored_request, delete_old_cache)
from lxml import html
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler
import schedule
import time
import logging
from config import valid_url_list, TOKEN
from telegram import ForceReply, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.error import Forbidden, BadRequest, NetworkError

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

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


async def add_search_command(update: Update, context):
    chat_id = update.effective_chat.id
    args = context.args

    if len(args) < 3:
        await update.message.reply_text(
            f"Usage: /add_search <url> <keyword> <max_price>\n")
        return

    url, keyword, max_price = args[0], args[1], args[2]

    if '.' in keyword and '-' in keyword:
        await update.message.reply_text(
            f"Usage: Do not use both AND(-) and OR(.) conditions in a single search\n")
        return


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
        message += f"ID: {search_id} | forum: {url.split('/')[-2]} | Keyword: {keyword} | Max Price: {max_price}\n"

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
    items_list = tree.xpath('//div[@data-tableid="topics"]/ol/li[5]/div[@class="ipsDataItem_main"]/h4/span[*]/a/@href')
    if items_list:
        item = items_list[-1]
    else:
        logger.info("Could not extract URL, skipping...")
        return 0
    return get_id_from_url(item)


def get_id_from_url(url):
    return url.split('/')[-2].split('-')[0]


async def run_checks_for_all_users(context: ContextTypes.DEFAULT_TYPE):
    searches = fetch_all_searches()
    logger.info("Fetched searches")
    bot = Bot(token=TOKEN)
    for search in searches:
        search_id, chat_id, url, keyword, max_price, last_match = search
        logger.info(f"Checking {search_id} search for new ads on {url}")
        await check_new_ads_for_search(bot, search_id, chat_id, url, keyword, max_price, last_match)
    delete_old_cache()


async def get_price_from_request(response):
    tree = html.fromstring(response.content)
    data = tree.xpath("//strong[contains(text(), 'Price') or contains(text(), 'Hinta')]/following-sibling::text()")
    raw = data[0] if len(data) else '0'
    value = re.sub(r'\D', '', raw)
    return int(value) if value else 0


async def is_listing_for_sale(response):
    tree = html.fromstring(response.content)
    data = tree.xpath("//h1[@class='ipsType_pageTitle ipsContained_container']/span/a/span")
    raw = data[0].text if len(data) else ''
    return raw == 'Myydään'


async def get_text_from_request(response):
    tree = html.fromstring(response.content)
    listing_text_fields = tree.xpath("//div[@data-role='commentContent'][1]//text()")
    with_geotag = ' '.join([text.strip() for text in listing_text_fields if text.strip()])
    with_geotag.replace(" City: ", " Paikkakunta: ")
    return with_geotag.split(" Paikkakunta: ")[0]


async def get_photo_from_request(response):
    tree = html.fromstring(response.content)
    img_url = tree.xpath("//strong[contains(text(), 'Price') or contains(text(), 'Hinta')]/../../p[*]/a/@href")
    if len(img_url):
        if img_url[0][:2] == '//':
            img_url[0] = img_url[0][2:]
    return img_url[0] if len(img_url) else 0

def is_search_content_in_page_multiple_keywords(keyword, page_contents):
    for word in keyword.split("-"):
        if word.lower() not in page_contents.lower():
            return False
    else:
        return True


def is_search_content_in_page_or_condition(keyword, page_contents):
    for word in keyword.split("."):
        if word.lower() in page_contents.lower():
            return True
    else:
        return False


def is_search_content_in_page(keyword, page_contents):
    if '-' in keyword:
        return is_search_content_in_page_multiple_keywords(keyword, page_contents)
    if '.' in keyword:
        return is_search_content_in_page_or_condition(keyword, page_contents)
    return keyword.lower() in page_contents.lower()


async def send_new_or_get_cached(url):
    cached_request = get_stored_request(url)
    if not cached_request:
        logger.info(f"Request to {url} was not cached")
        response = requests.get(url)
        serialized_data = pickle.dumps(response)
        create_stored_request(url, serialized_data)
        return response
    storage_id, url, data, timestamp = cached_request[0]
    if int(time.time()) - timestamp > 5 * 60:
        logger.info(f"Updating request cache to {url}")
        response = requests.get(url)
        serialized_data = pickle.dumps(response)
        update_stored_request(storage_id, serialized_data)
        return response
    logger.info(f"Getting {url} request from cache")
    return pickle.loads(data)


async def check_new_ads_for_search(bot, search_id, chat_id, url, keyword, max_price, last_match):
    response = await send_new_or_get_cached(f'{url}')
    price = 0
    listing_content = ''
    tree = html.fromstring(response.content)

    items = []
    list_items = tree.xpath('//div[@data-tableid="topics"]/ol/li')

    for li in list_items:
        link = li.xpath('.//div[@class="ipsDataItem_main"]/h4/span[2]/a/@href')
        if not link:
            link = li.xpath('.//div[@class="ipsDataItem_main"]/h4/span[1]/a/@href')
        if link:
            items.append(link[0])

    if not items:
        logger.info("No listings found, exiting...")
        return

    first_listing_id = get_id_from_url(items[0])

    for num, listing_url in enumerate(items):
        logger.info(f"Checking {num + 1} listing on page")

        if get_id_from_url(listing_url) == last_match:
            logger.info("Met last known listing")
            update_search(search_id, first_listing_id)
            break

        listing_response = await send_new_or_get_cached(listing_url)

        if listing_response.status_code == 200 and await is_listing_for_sale(listing_response):
            logger.info(f"Checking {num + 1} listing price")
            price = await get_price_from_request(listing_response)
            listing_content = await get_text_from_request(listing_response)

        if is_search_content_in_page(keyword, listing_content) and (price <= max_price or max_price == 0):
            logger.info(f"Trying to get attached image URL")
            img_url = await get_photo_from_request(listing_response)
            logger.info(f"Sending message to {chat_id}")
            try:
                if img_url:
                    await bot.send_photo(chat_id=chat_id, photo=img_url,
                                         caption=f"{listing_url} search ID {search_id}")
                else:
                    await bot.send_message(chat_id=chat_id, text=f"{listing_url} search ID {search_id}")
            except Forbidden:
                logger.info(f"User {chat_id} has blocked the bot. Skipping...")
            except BadRequest as e:
                logger.info(f"BadRequest error for {chat_id}: {e}")
            except NetworkError:
                logger.info("Network error, retrying later...")
    else:
        logger.info(f"Checked all listings on {url}, saving last ID to db")
        update_search(search_id, first_listing_id)


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
    application.job_queue.run_repeating(run_checks_for_all_users, 60)

    # application.job_queue.run_repeating(run_checks_for_all_users, 5)
    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
