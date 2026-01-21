from flask import Blueprint, render_template, request
from sqlite.database import init_db, add_participant, get_participants

participants_bp = Blueprint('participants', __name__)

init_db()  # Initialize database on blueprint load

@participants_bp.route('/')
@participants_bp.route('/home')
def index():
    return render_template('index.html')

@participants_bp.route('/join', methods=['GET', 'POST'])
def join():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        city = request.form['city']
        country = request.form['country']
        phone = request.form['phone']
        add_participant(name, email, city, country, phone)
        return render_template("index.html")
    else:
        return render_template('join.html')

@participants_bp.route('/participants')
def participants():
    data = get_participants()
    return render_template("participants.html", data=data)