# models.py

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# Option 1: Define db here and import it into app.py
# from flask import Flask # Only needed if creating app here too, not recommended
# app = Flask(__name__) # Example - don't do this if db is defined in app.py
# app.config['SQLALCHEMY_DATABASE_URI'] = 'your_db_uri' # Needs config too
# db = SQLAlchemy(app)

# Option 2 (Preferred based on your app.py structure):
# Import the 'db' object created in app.py
# This avoids circular dependencies if models don't need to import app directly.
# We need to find a way for models.py to know about the 'db' instance from app.py
# without importing 'app' itself directly back.
# A common pattern is to create db in a separate extension file,
# or initialize it in app.py BEFORE importing models.
# Your current app.py structure (db = SQLAlchemy(app); from models import ...) suggests this:
# db must be importable here. Let's assume db is created in app.py and we can import it.
# This requires careful initialization order in app.py.

# Let's try importing db directly from app first, though it can cause issues.
# A better pattern would be to create db = SQLAlchemy() here or in an extensions.py
# and then call db.init_app(app) in app.py.
# For now, let's assume app.py creates db = SQLAlchemy(app) *before* it imports models.
# This means models.py SHOULD NOT import 'app' but needs 'db' somehow.

# --> Simplest Approach given current app.py: Define db *here*
#     and import it *into* app.py. This reverses the dependency.

db = SQLAlchemy() # Create the SQLAlchemy object instance here

# --- Model Definitions ---

class AppSetting(db.Model):
    """Stores application settings as key-value pairs."""
    __tablename__ = 'app_settings' # Optional: define a table name

    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    setting_value = db.Column(db.Text, nullable=True) # Use Text for potentially long values
    description = db.Column(db.String(255), nullable=True) # Optional: Add description for Admin UI

    def __repr__(self):
        return f'<AppSetting {self.setting_key}={self.setting_value[:20]}>'


class Response(db.Model):
    """Stores user responses to trivia questions."""
    __tablename__ = 'responses' # Optional: define a table name

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(100), nullable=True, index=True) # Or link to a User model if you add users
    wiki_page_title = db.Column(db.String(255), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    answer_options = db.Column(db.Text, nullable=True) # Store JSON as string, or use JSON type if DB supports it
    correct_answer = db.Column(db.String(10), nullable=False) # e.g., 'A', 'B', 'C', 'D'
    user_answer = db.Column(db.String(10), nullable=True)
    user_confidence = db.Column(db.Integer, nullable=True) # Storing 0-100
    is_correct = db.Column(db.Boolean, nullable=True)
    brier_score = db.Column(db.Float, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f'<Response id={self.id} correct={self.is_correct} confidence={self.user_confidence}>'