import sqlite3


def init_db():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()

    # Create user_data table to store user chat_id
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_data (
                        chat_id INTEGER PRIMARY KEY)''')

    # Create user_searches table to store each search
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_searches (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER,
                        url TEXT,
                        keyword TEXT,
                        max_price INTEGER,
                        last_match TEXT,
                        FOREIGN KEY (chat_id) REFERENCES user_data (chat_id))''')

    conn.commit()
    conn.close()


def add_search(chat_id, url, keyword, max_price, last_match):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()

    # Insert the search into the user_searches table
    cursor.execute('''INSERT INTO user_searches (chat_id, url, keyword, max_price, last_match)
                      VALUES (?, ?, ?, ?, ?)''', (chat_id, url, keyword, max_price, last_match))

    conn.commit()
    conn.close()


def update_search(search_id, last_match):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('''UPDATE user_searches SET last_match = ? where id = ?''', (last_match, search_id))

    conn.commit()
    conn.close()


# Function to delete a search by ID
def delete_search(chat_id, search_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()

    # Delete the search where id matches
    cursor.execute('''DELETE FROM user_searches WHERE chat_id = ? AND id = ?''', (chat_id, search_id))

    conn.commit()
    conn.close()


# Function to list all searches for a user
def list_searches(chat_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()

    # Select all searches for the specific user
    cursor.execute('''SELECT id, url, keyword, max_price FROM user_searches WHERE chat_id = ?''', (chat_id,))
    searches = cursor.fetchall()

    conn.close()
    return searches


# Function to fetch all searches for all users (for the scheduled scraping)
def fetch_all_searches():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()

    # Fetch all user searches
    cursor.execute('''SELECT id, chat_id, url, keyword, max_price, last_match FROM user_searches''')
    searches = cursor.fetchall()

    conn.close()
    return searches
