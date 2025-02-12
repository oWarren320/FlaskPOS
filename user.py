from app import app, db
from models import User

with app.app_context():
    cashier = User(username='Peter', role='cashier')
    cashier.set_password('9090')
    db.session.add(cashier)
    db.session.commit()