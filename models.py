from datetime import datetime
import pytz
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship
from werkzeug.security import generate_password_hash, check_password_hash

# Initialize SQLAlchemy
db = SQLAlchemy()

# Define East Africa Timezone
eat = pytz.timezone('Africa/Nairobi')

# User Model
class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), default='cashier')
    status = db.Column(db.String(20), default='active')

    # Relationships
    orders = db.relationship('Order', backref='user', lazy=True)

    def set_password(self, password):
        """Hash and set the user's password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verify the user's password."""
        return check_password_hash(self.password_hash, password)

    def deactivate(self):
        """Soft delete: Set user status to inactive"""
        self.status = "inactive"
        db.session.commit()

    def activate(self):
        """Reactivate user"""
        self.status = "active"
        db.session.commit()

    def __repr__(self):
        return f'<User {self.username} ({self.status})>'

# Product Model
class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    product_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    price = db.Column(db.Float, nullable=False)
    buying_price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(10), nullable=False, default='active')

    # Relationships
    order_items = db.relationship('OrderItem', back_populates='product')

    def deactivate(self):
        """Soft delete product by setting status to inactive."""
        self.status = 'inactive'
        db.session.commit()

    def activate(self):
        """Restore product by setting status to active."""
        self.status = 'active'
        db.session.commit()

    def __repr__(self):
        return f'<Product {self.product_name} ({self.status})>'

# Order Model
class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='Completed')
    cash_amount = db.Column(db.Float, default=0.0)  # Cash portion of the payment
    mpesa_amount = db.Column(db.Float, default=0.0)
    payment_type = db.Column(db.String(20), nullable=False)
    amount_received = db.Column(db.Float, nullable=False)# e.g., 'pending', 'completed', 'cancelled'
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(eat))

    # Relationships
    items = db.relationship('OrderItem', back_populates='order')

    def __repr__(self):
        return f'<Order {self.id}>'

# OrderItem Model (Many-to-Many relationship between Order and Product)
class OrderItem(db.Model):
    __tablename__ = 'order_items'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)

    # Relationships
    order = relationship('Order', back_populates='items')
    product = db.relationship('Product', back_populates='order_items')

    def get_product_name(self):
        """Convenience method to get the product name."""
        return self.product.product_name


    def __repr__(self):
        return f'<OrderItem {self.id}>'


class StockRequest(db.Model):
    __tablename__ = 'stock_requests'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    requested_stock = db.Column(db.Integer, nullable=False)
    requested_buying_price = db.Column(db.Float, nullable=False)
    requested_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # Second foreign key to User
    status = db.Column(db.String(20), default='pending')

    # Relationships
    product = db.relationship('Product', backref='stock_requests')

    # Explicitly specify which foreign key belongs to each relationship
    user = db.relationship('User', foreign_keys=[user_id], backref='user_stock_requests')
    requester = db.relationship('User', foreign_keys=[requested_by], backref='requested_stock_requests')

    def __repr__(self):
        return f'<StockRequest {self.id}>'
