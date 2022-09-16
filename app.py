import os

import sqlite3
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd
from datetime import datetime

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Custom filter
app.jinja_env.filters["usd"] = usd  # type: ignore

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

sqlite_connection = sqlite3.connect("finance.db", check_same_thread=False)
sqlite_connection.row_factory = sqlite3.Row
cursor = sqlite_connection.cursor()

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")

def my_upper(string):
    return string.upper()

def my_round(num):
    return round(num, 2)

app.jinja_env.globals.update(lookup=lookup) # type: ignore
app.jinja_env.globals.update(round=my_round) # type: ignore
app.jinja_env.globals.update(upper=my_upper) # type: ignore

def get_user():
    user_id = session["user_id"]
    users = cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    users = cursor.fetchall()
    users = [dict(user) for user in users]
    user = users[0]
    return user

def get_purchase_list():
    user_id = session["user_id"]
    purchase_list = cursor.execute("SELECT * FROM purchases WHERE user_id = ?", (user_id,))
    purchase_list = cursor.fetchall()
    purchase_list = [dict(purchase) for purchase in purchase_list]
    return purchase_list

def get_sell_list():
    user_id = session["user_id"]
    sell_list = cursor.execute("SELECT * FROM sells WHERE user_id = ?", (user_id,))
    sell_list = cursor.fetchall()
    sell_list = [dict(sell) for sell in sell_list]
    return sell_list

# returns string like '15/09/2022, 12:17:04'
def get_date():
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")

def get_current_stock_list():
    user_id = session["user_id"]
    current_stock_list = cursor.execute("SELECT * FROM current_stocks WHERE user_id = ?", (user_id,))
    current_stock_list = cursor.fetchall()
    current_stock_list = [dict(current_stock) for current_stock in current_stock_list]
    return current_stock_list

@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    # need to get these: user obj, stock list, total value of stock
    user = get_user()
    stock_list = get_current_stock_list()
    #[{"symbol": "googl", "shares": 10}, {"symbol": "nflx", "shares": 5}]
    #next(item for item in a if item["symbol"] == "googl")
    #stock_list = [{purchase["symbol"]: purchase["shares"]} for purchase in purchase_list]
    
    stock_values = [lookup(stock["symbol"])["price"] * stock["shares"] for stock in stock_list] # type: ignore
    return render_template("portfolio.html", user=user, stock_list=stock_list, total_stock_value=sum(stock_values))


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "POST":
        symbol = request.form.get("symbol")  # type: ignore
        if not symbol:
            return apology("must provide symbol", 403)
        stock_quote = lookup(symbol)
        if stock_quote is None:
            return apology("no stock with that symbol found", 404)
        shares = request.form.get("shares")  # type: ignore
        if not shares:
            return apology("must provide shares", 403)
        shares = int(shares)
        if shares <= 0:
            return apology("must provide positive number of shares", 403)
        stock_price = stock_quote["price"]
        batch_price = stock_price * shares

        # can be replaced by user = get_user()
        user = get_user()
        user_id = user["id"]

        user_funds = user["cash"]
        if batch_price > user_funds:
            return apology("you're too broke, can't afford stonks :(", 403)

        updated_funds = user_funds - batch_price
        cursor.execute("UPDATE users SET cash = ? WHERE id = ?", (updated_funds, user_id))
        sqlite_connection.commit()

        date = get_date()
        cursor.execute("INSERT INTO purchases (user_id, symbol, shares, batch_price, datetime) VALUES (?,?,?,?,?)", (user_id, symbol, shares, batch_price, date))  # type: ignore
        sqlite_connection.commit()

        existing_stock = cursor.execute("SELECT * FROM current_stocks WHERE symbol = ? AND user_id = ?", (symbol, user_id))
        existing_stock = cursor.fetchall()
        existing_stock = [dict(stock) for stock in existing_stock]
        print(f"existing stock: {existing_stock}, {type(existing_stock)}")
        # insert (if symbol not exists)
        if not existing_stock:
            cursor.execute("INSERT INTO current_stocks (user_id, symbol, shares) VALUES (?,?,?)", (user_id, symbol, shares))
            sqlite_connection.commit()
        else:
            existing_stock = existing_stock[0]
            # update (add shares)
            updated_shares = existing_stock["shares"] + shares
            cursor.execute("UPDATE current_stocks SET shares = ? WHERE symbol = ? AND user_id = ?", (updated_shares, symbol, user_id))
            sqlite_connection.commit()

        
        return redirect("/")

    elif request.method == "GET":
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    # note for bdays project: datetime object - datetime object can give u difference in time
    # can use that to sort whose bday is closest n sleep for that time with background scheduler

    # pull records from each table (purchases n sells)
    purchase_list = get_purchase_list()
    sell_list = get_sell_list()
    # combine to one dict
    history = purchase_list + sell_list
    # sort list based on dictionary value
    # newlist = sorted(list_to_be_sorted, key=lambda d: d['name']) 
    chronological_history = sorted(history, key=lambda d: d['datetime'])
    # label record as buy or sell
    for transaction in chronological_history:
        if "purchase_id" in transaction:
            transaction["type"] = "BUY"
        elif "sell_id" in transaction:
            transaction["type"] = "SELL"
    # pass to the html
    return render_template("history.html", stock_history=chronological_history)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()  # type: ignore

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):  # type: ignore
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):  # type: ignore
            return apology("must provide password", 403)

        # Query database for username
        rows = cursor.execute("SELECT * FROM users WHERE username = ?", (request.form.get("username"),))  # type: ignore
        rows = cursor.fetchall()
        rows = [dict(row) for row in rows]

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):    # type: ignore
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()  # type: ignore

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":
        symbol = request.form.get("symbol")  # type: ignore
        stock_quote = lookup(symbol)
        if stock_quote is None:
            return apology("invalid stock quote", 404)
        return render_template("quoted.html", stock_quote=stock_quote) 

    elif request.method == "GET":
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "POST":
        if not request.form.get("username"):  # type: ignore
            return apology("must provide username", 403)
        elif not request.form.get("password"):  # type: ignore
            return apology("must provide password", 403)
        elif not request.form.get("confirmation"):  # type: ignore
            return apology("please fill re-enter password field", 403)
        elif not request.form.get("password") == request.form.get("confirmation"):  # type: ignore
            return apology("passwords do not match, try again", 403)
        
        cursor.execute("INSERT INTO users (username, hash) VALUES (?,?)", (request.form.get("username"), generate_password_hash(request.form.get("password"))))  # type: ignore
        sqlite_connection.commit()

        return redirect("/")

    elif request.method == "GET":
        return render_template("registration.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    if request.method == "POST":
        symbol = request.form.get("symbol") # type: ignore
        if not symbol:  
            return apology("must select a stock symbol", 403)
        current_stock_list = get_current_stock_list()
        
        stock_to_sell = None
        for stock in current_stock_list:
            if stock["symbol"] == symbol:
                stock_to_sell = stock
        if stock_to_sell is None:
            return apology("you have not bought shares for this company", 403)

        shares_to_sell = request.form.get("shares")  # type: ignore
        if not shares_to_sell:
            return apology("must provide shares", 403)
        shares_to_sell = int(shares_to_sell)
        if shares_to_sell <= 0:
            return apology("must provide positive number of shares", 403)

        if stock_to_sell["shares"] < shares_to_sell:
            return apology("you don't have enough shares to sell", 403)

        # calculate batch price
        batch_price = lookup(symbol)["price"] * shares_to_sell # type: ignore
        
        # update users cash (update on users table)
        user = get_user()
        user_id = user["id"]
        updated_funds = user["cash"] + batch_price
        cursor.execute("UPDATE users SET cash = ? WHERE id = ?", (updated_funds, user_id))
        sqlite_connection.commit()

        # add new sell record into sells (insert on sells table)
        date = get_date()
        cursor.execute("INSERT INTO sells (user_id, symbol, shares, batch_price, datetime) VALUES (?,?,?,?,?)", (user_id, symbol, shares_to_sell, batch_price, date))  # type: ignore
        sqlite_connection.commit()

        # update (minus shares)
        existing_stock = cursor.execute("SELECT * FROM current_stocks WHERE symbol = ? AND user_id = ?", (symbol, user_id))
        existing_stock = cursor.fetchall()
        existing_stock = [dict(stock) for stock in existing_stock]
        existing_stock = existing_stock[0]

        updated_shares = existing_stock["shares"] - shares_to_sell
        cursor.execute("UPDATE current_stocks SET shares = ? WHERE symbol = ? AND user_id = ?", (updated_shares, symbol, user_id))
        sqlite_connection.commit()
        
        return redirect("/")
    elif request.method == "GET":
        return render_template("sell.html", stock_list=get_current_stock_list())
