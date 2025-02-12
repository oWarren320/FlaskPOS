from datetime import datetime, timedelta, date
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from flask_login import LoginManager, login_user, login_required, current_user, logout_user
from flask_migrate import Migrate
from sqlalchemy import func
from werkzeug.security import generate_password_hash
from sqlalchemy.orm import joinedload

from models import db, User, Product, Order, OrderItem, StockRequest

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'  # SQLite database
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'your_secret_key_here'  # Required for session management

# Initialize the database
db.init_app(app)

# Initialize Flask-Migrate
migrate = Migrate(app, db)

# Initialize Flask-Login
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    """Load the user object from the user ID stored in the session."""
    return User.query.get(int(user_id))

# Create tables
with app.app_context():
    db.create_all()

def get_start_date(filter_option, today):
    """
    Calculate the start date based on the filter option.

    Args:
        filter_option (str): The filter option ('day', 'week', or 'month').
        today (datetime): The current date and time.

    Returns:
        datetime: The start date based on the filter.
    """
    if filter_option == 'week':
        # Start of the week (Monday)
        return (today - timedelta(days=today.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    elif filter_option == 'month':
        # Start of the month
        return today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        # Default to start of the day
        return today.replace(hour=0, minute=0, second=0, microsecond=0)

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        pin = request.form.get('pin')

        # Query the database for the user
        user = User.query.filter_by(username=username).first()

        # Check if the user exists, is active, and the PIN matches
        if user and user.status == 'active' and user.check_password(pin):
            login_user(user)  # Log the user in

            # Redirect to the appropriate dashboard based on the user's role
            if user.role == 'cashier':
                return redirect(url_for('cashier_dashboard'))
            else:
                return redirect(url_for('admin_dashboard'))
        else:
            # Flash an error message for invalid login
            jsonify('Invalid username, PIN, or account is inactive', 'error')
            return redirect(url_for('login'))  # Redirect back to the login page

    # Render the login page for GET requests
    return render_template('login.html')

@app.route('/cashier_dashboard')
@login_required
def cashier_dashboard():
    # Ensure the user is a cashier
    if current_user.role != 'cashier':
        return redirect(url_for('admin_dashboard'))

    # Fetch products from the database
    search_query = request.args.get('search', '')
    if search_query:
        products = Product.query.filter(Product.name.contains(search_query)).all()
    else:
        products = Product.query.all()

    return render_template('cashier_dashboard.html', products=products)

@app.route('/record_sale', methods=['GET', 'POST'])
@login_required
def record_sale():
    if current_user.role != "cashier":
        return jsonify({"error": "Unauthorized access!"}), 403 # Forbidden

    # Fetch products for the dropdown
    products = Product.query.all()

    if request.method == 'POST':
        try:
            # Get form data
            product_ids = request.form.getlist('product_id[]')
            quantities = request.form.getlist('quantity[]')
            payment_type = request.form.get('payment_type')
            amount_received = request.form.get('amount_received', type=float)
            cash_received = request.form.get('cash_received', type=float)
            mpesa_received = request.form.get('mpesa_received', type=float)

            # Validate required fields
            if not product_ids or not quantities or not payment_type:
                return jsonify({
                    "error": "All fields are required."
                }), 400

            # Validate quantities and product IDs
            if len(product_ids) != len(quantities):
                return jsonify({
                    "error": "Mismatch between products and quantities."
                }), 400

            # Calculate grand total
            grand_total = 0
            items = []
            for product_id, quantity in zip(product_ids, quantities):
                product = Product.query.get(product_id)
                if not product:
                    return jsonify({
                        "error": f"Product with ID {product_id} not found."
                    }), 404
                if product.stock < int(quantity):
                    return jsonify({
                        "error": f"Insufficient stock for product: {product.product_name}."
                    }), 400  # Bad Request
                grand_total += product.price * int(quantity)
                items.append({
                    'name': product.product_name,
                    'quantity': int(quantity),
                    'price': product.price
                })

            # Validate payment amounts
            if payment_type == 'Partial':
                if not cash_received or not mpesa_received:
                    return jsonify({
                        "error": f"Cash and M-Pesa amounts are required for partial payments."
                    }), 400  # Bad Request
                if (cash_received + mpesa_received) != grand_total:
                    return jsonify({
                        "error": f"Cash and M-Pesa amounts must add up to the grand total."
                    }), 400  # Bad Request
            elif payment_type in ['Cash', 'M-Pesa']:
                if not amount_received or amount_received != grand_total:
                    return jsonify({
                        "error" : "Amount received must match the grand total for {payment_type} payments."
                    }), 400  # Bad Request
            else:
                return jsonify({
                    "error" : "Invalid payment type."
                }), 400  # Bad Request

            # Create a single sale record for the entire transaction
            sale = Order(
                user_id=current_user.id,
                total_amount=grand_total,  # Total price for the entire sale
                payment_type=payment_type,
                cash_amount=cash_received if payment_type == 'Partial' else (
                    amount_received if payment_type == 'Cash' else 0),
                mpesa_amount=mpesa_received if payment_type == 'Partial' else (
                    amount_received if payment_type == 'M-Pesa' else 0),
                amount_received=(
                    cash_received + mpesa_received if payment_type == 'Partial' else amount_received
                )
            )

            db.session.add(sale)
            db.session.flush()

            # Deduct stock and create sale items
            for product_id, quantity in zip(product_ids, quantities):
                product = Product.query.get(product_id)
                if product.stock < int(quantity):
                    db.session.rollback()
                    return jsonify({
                        "error" : f"Insufficient stock for product: {product.name}."
                    }), 400  # Bad Request
                product.stock -= int(quantity)

                # Create a sale item record
                sale_item = OrderItem(
                    order_id=sale.id,
                    product_id=product_id,
                    quantity=int(quantity),
                    price=product.price  # Store the price per unit
                )
                db.session.add(sale_item)

            db.session.commit()

            '''# Store the sale data in session for the sale_success route
            session['sale_data'] = {
                'items': items,
                'total_price': grand_total,
                'payment_type': payment_type,
                'change': amount_received - grand_total if payment_type in ['Cash', 'M-Pesa'] else 0,
                'now': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }'''

            if 'sale_data' not in session:
                session['sale_data'] = {}  # Ensure session key exists

            session['sale_data'].update({
                'items': items,
                'total_price': grand_total,
                'payment_type': payment_type,
                'change': amount_received - grand_total if payment_type in ['Cash', 'M-Pesa'] else 0,
                'now': datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # Ensuring 'now' is always included
            })

            session.modified = True

            return jsonify({'redirect': url_for('sale_success')})

        except Exception as e:
            db.session.rollback()
            return jsonify({
                "error" : f'An error occurred: {str(e)}'
            }), 500  # Internal Server Error

    # Render the record_sales template for GET requests
    return render_template('record_sales.html', products=products)

@app.route('/sale_success')
@login_required
def sale_success():
    # Retrieve sale data from session
    sale_data = session.get('sale_data')

    if not sale_data:
        return jsonify({"error": "No sale data found."}), 404  # Not Found

    # Ensure default values to avoid Jinja errors
    items = sale_data.get('items', [])
    total_price = sale_data.get('total_price', 0)
    payment_type = sale_data.get('payment_type', 'Unknown')
    change = sale_data.get('change', 0)
    now = sale_data.get('now', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    # Clear the session data after retrieving it
    session.pop('sale_data', None)

    return render_template(
        'sale_success.html',
        sale_data=sale_data,  # Ensure it's passed
        items=items,
        total_price=total_price,
        payment_type=payment_type,
        change=change,
        now=now
    )

@app.route('/sales_reconciliation')
def sales_reconciliation():
    filter = request.args.get('filter', 'day')  # Default filter to 'day'

    # Get current date & time
    now = datetime.now()
    start_of_today = datetime.combine(date.today(), datetime.min.time())

    # Determine filter range
    if filter == 'day':
        start_time = start_of_today
    elif filter == 'week':
        start_time = start_of_today - timedelta(days=start_of_today.weekday())  # Start of week
    elif filter == 'month':
        start_time = datetime.combine(date.today().replace(day=1), datetime.min.time())  # Start of month
    else:
        start_time = None  # Fetch all records

    # Query database with optimization
    query = db.session.query(Order).options(joinedload(Order.items))

    if start_time:
        query = query.filter(Order.created_at >= start_time)

    sales = query.all()

    # Process data for JSON response
    sales_data = []
    for order in sales:
        for item in order.items:
            sales_data.append({
                'date': order.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'product': item.product.product_name,
                'quantity': item.quantity,
                'total_amount': item.price * item.quantity,
                'cash_amount': order.cash_amount if order.payment_type in ["Cash", "Both"] else 0,
                'mpesa_amount': order.mpesa_amount if order.payment_type in ["Mpesa", "Both"] else 0,
                'payment_type': order.payment_type
            })

    # Calculate totals
    total_sales = sum(sale['total_amount'] for sale in sales_data)
    cash_sales = sum(sale['cash_amount'] for sale in sales_data)
    mpesa_sales = sum(sale['mpesa_amount'] for sale in sales_data)

    # Return JSON if AJAX request
    if request.args.get('filter'):
        return jsonify({
            'sales': sales_data,
            'total_sales': total_sales,
            'cash_sales': cash_sales,
            'mpesa_sales': mpesa_sales
        })

    # Render the template for initial page load
    return render_template('sales_reconciliation.html', sales=sales_data, total_sales=total_sales,
                           cash_sales=cash_sales, mpesa_sales=mpesa_sales)

@app.route('/update_stock', methods=['GET', 'POST'])
@login_required
def update_stock():
    if request.method == 'GET':
        # Fetch products for the dropdown
        products = Product.query.all()
        return render_template('update_stock.html', products=products)

    elif request.method == 'POST':
        try:
            # Parse form data
            product_id = request.form.get('product_id')
            new_stock = request.form.get('stock')
            buying_price = request.form.get('buying_price')

            # Ensure numeric values are valid
            if not product_id or not new_stock or not buying_price:
                return jsonify({"error": "All fields are required"}), 400  # Bad Request

            new_stock = int(new_stock)
            buying_price = float(buying_price)

            # Fetch the product
            product = Product.query.get(product_id)
            if not product:
                return jsonify({"error": "Product not found"}), 404  # Not Found

            # Ensure user exists
            user = User.query.get(current_user.id)
            if not user:
                return jsonify({"error": "User not found"}), 400  # Bad Request

            # Create a stock update request
            stock_update_request = StockRequest(
                product_id=product.id,
                user_id=user.id,  # Ensuring user_id is set
                requested_stock=new_stock,
                requested_buying_price=buying_price,
                requested_by=user.id,  # Ensuring requested_by is set correctly
                status='pending'
            )

            db.session.add(stock_update_request)
            db.session.commit()

            success_message = f"Stock update request for {product.product_name} has been submitted."
            return render_template('update_stock.html', products=Product.query.all(), success_message=success_message)

        except ValueError:
            db.session.rollback()
            return jsonify({"error": "Invalid data format. Ensure numbers are correctly entered."}), 400

        except Exception as e:
            db.session.rollback()
            return jsonify({"error": f"An error occurred: {str(e)}"}), 500  # Internal Server Error


@app.route('/admin_dashboard')
@login_required
def admin_dashboard():
    # Check if the user is an admin
    if current_user.role != 'admin':
        return jsonify({
            "error" : 'You do not have permission to access this page.'
        }), 403  # Forbidden

    # Fetch data for the dashboard
    total_sales = Order.query.with_entities(db.func.sum(Order.total_amount)).scalar() or 0
    total_stock = Product.query.with_entities(db.func.sum(Product.stock)).scalar() or 0
    total_users = User.query.count()

    return render_template('admin_dashboard.html',
                           total_sales=total_sales,
                           total_stock=total_stock,
                           total_users=total_users)

@app.route('/view_stock')
@login_required
def view_stock():
    # Ensure the user is an admin
    if current_user.role != 'admin':
        return jsonify({
            " error": 'You do not have permission to access this page.'
        }), 403  # Forbidden

    # Fetch all products
    products = Product.query.all()
    return render_template('view_stock.html', products=products)

@app.route('/manage_users', methods=['GET', 'POST'])
@login_required
def manage_users():
    # Ensure the user is an admin
    if current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        # Handle form submission (adding a new user)
        username = request.form.get('username')
        pin = request.form.get('pin')
        role = request.form.get('role')

        # Validate input
        if not username or not pin or len(pin) != 6:
            return jsonify({"error": "Invalid input. PIN must be 6 digits."}), 400

        if role not in ['admin', 'cashier']:  # Validate role
            return jsonify({"error": "Invalid role. Must be 'admin' or 'cashier'."}), 400

        # Check if username already exists
        if User.query.filter_by(username=username).first():
            return jsonify({"error": "Username already exists."}), 400

        # Hash the PIN and create the user
        hashed_password = generate_password_hash(pin)
        new_user = User(username=username, password_hash=hashed_password, role=role)
        db.session.add(new_user)
        db.session.commit()

        flash(f'User {username} added successfully!', 'success')
        return jsonify({'status': 'success', 'message': f'User {username} added successfully!'})

    # Handle GET request (display the manage users page)
    users = User.query.all()
    return render_template('manage_users.html', users=users)


@app.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if current_user.role != 'admin':
        return jsonify({
            'status': 'error',
            'message': 'Access denied.'
        }), 403  # Forbidden

    user = User.query.get_or_404(user_id)

    # Prevent admin from deactivating themselves
    if user.id == current_user.id:
        return jsonify({
            'status': 'error',
            'message': 'You cannot deactivate yourself!'
        }), 400  # Bad Request

    user.status = "inactive"  # Soft delete by updating status
    db.session.commit()

    return jsonify({
        'status': 'success',
        'message': f'User {user.username} has been deactivated.'
    })

@app.route('/reactivate_user/<int:user_id>', methods=['POST'])
@login_required
def reactivate_user(user_id):
    if current_user.role != 'admin':
        return jsonify({
            'status': 'error',
            'message': 'Access denied.'
        }), 403  # Forbidden

    user = User.query.get_or_404(user_id)
    user.status = "active"  # Reactivate user
    db.session.commit()

    return jsonify({
        'status': 'success',
        'message': f'User {user.username} has been reactivated.'
    })

@app.route('/add_product', methods=['POST'])
@login_required
def add_product():
    if current_user.role != 'admin':
        return jsonify({
            'status': 'error',
            'message': 'You do not have permission to perform this action.'
        }), 403  # Forbidden

    try:
        # Parse form data
        product_name = request.form.get('product_name')
        quantity = int(request.form.get('quantity'))
        price = float(request.form.get('price'))
        buying_price = float(request.form.get('buying_price'))  # Add this line

        # Validate input
        if not product_name or quantity < 0 or price < 0 or buying_price < 0:
            return jsonify({
                'status': 'error',
                'message': 'Invalid input. Please check the form fields.'
            }), 400  # Bad Request

        # Create a new product
        new_product = Product(
            product_name=product_name,
            stock=quantity,
            price=price,
            buying_price=buying_price  # Include buying_price
        )
        db.session.add(new_product)
        db.session.commit()

        return jsonify({
            'status': 'success',
            'message': 'Product added successfully!'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'status': 'error',
            'message': f'An error occurred: {str(e)}'
        }), 500  # Internal Server Error

from flask import request, jsonify, render_template

@app.route('/edit_product/<int:product_id>', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    if current_user.role != 'admin':
        return jsonify({"error": "You do not have permission to perform this action."}), 403

    product = Product.query.get_or_404(product_id)

    if request.method == 'POST':
        try:
            product.product_name = request.form.get('product_name')
            product.buying_price = float(request.form.get('buying_price', 0))
            product.price = float(request.form.get('price', 0))
            db.session.commit()

            # Check if it's an AJAX request
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({"success": True, "message": f"Product '{product.product_name}' updated successfully!"})

            # If it's a normal request, redirect to the edit page
            flash(f"Product '{product.product_name}' updated successfully!", "success")
            return redirect(url_for('edit_product', product_id=product.id))

        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "message": f"An error occurred: {str(e)}"}), 500

    return render_template('edit_product.html', product=product)



@app.route('/delete_product/<int:product_id>', methods=['POST'])
@login_required
def delete_product(product_id):
    # Ensure the user is an admin
    if current_user.role != 'admin':
        return jsonify({
            'status': 'error',
            'message': 'You do not have permission to perform this action.'
        }), 403  # Forbidden

    # Fetch the product
    product = Product.query.get_or_404(product_id)

    try:
        # Soft delete the product by setting its status to 'inactive'
        product.deactivate()
        return jsonify({
            'status': 'success',
            'message': 'Product deactivated successfully!'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            "error" : f'An error occurred: {str(e)}'
        }), 500  # Internal Server Error


@app.route('/approve_stock', methods=['GET', 'POST'])
@login_required
def approve_stock():
    if current_user.role != 'admin':
        return jsonify({"error": 'Access denied. Admins only.'}), 403  # Forbidden

    if request.method == 'POST':
        request_id = request.form.get('request_id')
        action = request.form.get('action')

        stock_request = StockRequest.query.get_or_404(request_id)

        if action == 'approve':
            product = stock_request.product
            product.stock += stock_request.requested_stock
            product.buying_price = stock_request.requested_buying_price
            db.session.delete(stock_request)
            db.session.commit()
            flash(f"Stock approval for {product.product_name} completed successfully.", 'success')

        elif action == 'reject':
            db.session.delete(stock_request)
            db.session.commit()
            flash(f"Stock rejection for {stock_request.product.product_name} completed successfully.", 'warning')

        return redirect(url_for('approve_stock'))

    requests = StockRequest.query.all()
    return render_template('approve_stock.html', requests=requests)


@app.route('/view_sales_report', methods=['GET'])
@login_required
def view_sales_report():
    if current_user.role != 'admin':
        return jsonify({
            'status': 'error',
            'message': 'Access denied. Admins only.'
        }), 403  # Forbidden

    # Get date range filter from query parameters
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    # Fetch all orders (filtered by date range if provided)
    query = Order.query

    if start_date and end_date:
        try:
            start_date = datetime.strptime(start_date, '%Y-%m-%d')
            end_date = datetime.strptime(end_date, '%Y-%m-%d')
            query = query.filter(Order.created_at >= start_date, Order.created_at <= end_date)
        except ValueError:
            return jsonify({
                'status': 'error',
                'message': 'Invalid date format. Use YYYY-MM-DD.'
            }), 400  # Bad Request

    orders = query.all()

    # Calculate total sales
    total_sales = sum(order.total_amount for order in orders)

    # Calculate sales by product
    sales_by_product = db.session.query(
        Product.product_name,
        func.sum(OrderItem.quantity).label('total_quantity'),
        func.sum(OrderItem.price * OrderItem.quantity).label('total_sales')
    ).join(OrderItem, Product.id == OrderItem.product_id
    ).join(Order, OrderItem.order_id == Order.id
    ).group_by(Product.product_name).all()

    # Calculate sales by payment type
    sales_by_payment_type = db.session.query(
        Order.payment_type,
        func.sum(Order.total_amount).label('total_sales')
    ).group_by(Order.payment_type).all()

    return render_template('view_sales_report.html',
                           total_sales=total_sales,
                           sales_by_product=sales_by_product,
                           sales_by_payment_type=sales_by_payment_type,
                           start_date=start_date,
                           end_date=end_date)

@app.route('/logout')
@login_required
def logout():
    logout_user()  # Log the user out
    return render_template('login.html')

if __name__ == '__main__':
    app.run(debug=True)