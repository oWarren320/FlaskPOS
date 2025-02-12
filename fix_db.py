from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import SQLAlchemyError

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'  # Change to your DB
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class StockRequest(db.Model):
    __tablename__ = 'stock_requests'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    requested_stock = db.Column(db.Integer, nullable=False)
    requested_buying_price = db.Column(db.Float, nullable=False)
    requested_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # Ensure this is correct
    status = db.Column(db.String(20), default='pending')

    product = db.relationship('Product', backref='stock_requests')
    user = db.relationship('User', backref='stock_requests', foreign_keys=[user_id])
    requested_user = db.relationship('User', backref='requested_stock_requests', foreign_keys=[requested_by])

    def __repr__(self):
        return f'<StockRequest {self.id}>'


def recreate_stock_requests():
    try:
        print("Dropping existing stock_requests table...")
        db.session.execute('DROP TABLE IF EXISTS stock_requests')
        db.session.commit()

        print("Creating new stock_requests table...")
        db.create_all()  # Recreate tables with new structure
        print("Success! Table recreated.")

    except SQLAlchemyError as e:
        print(f"Error: {str(e)}")
        db.session.rollback()


if __name__ == '__main__':
    with app.app_context():
        recreate_stock_requests()
