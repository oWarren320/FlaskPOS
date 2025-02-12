from app import app, db
from models import User

with app.app_context():
    user = User(username='administrator', role='admin')
    user.set_password('1234')  # Set the PIN/password
    db.session.add(user)
    db.session.commit()