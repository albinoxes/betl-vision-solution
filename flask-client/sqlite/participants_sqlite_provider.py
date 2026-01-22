import sqlite3

def init_db():
    connect = sqlite3.connect('database.db')
    connect.execute(
        'CREATE TABLE IF NOT EXISTS PARTICIPANTS (name TEXT, \
        email TEXT, city TEXT, country TEXT, phone TEXT)')
    connect.close()

def add_participant(name, email, city, country, phone):
    with sqlite3.connect("database.db") as users:
        cursor = users.cursor()
        cursor.execute("INSERT INTO PARTICIPANTS \
        (name,email,city,country,phone) VALUES (?,?,?,?,?)",
                       (name, email, city, country, phone))
        users.commit()

def get_participants():
    connect = sqlite3.connect('database.db')
    cursor = connect.cursor()
    cursor.execute('SELECT * FROM PARTICIPANTS')
    data = cursor.fetchall()
    connect.close()
    return data