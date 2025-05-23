# models.py

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

# --- Model Definitions ---

class User(db.Model): # NEW MODEL
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    nickname = db.Column(db.String(80), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    # Future fields: email, password_hash, last_login, etc.

    def __repr__(self):
        return f'<User {self.id} {self.nickname}>'
    
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
    __tablename__ = 'responses'
    id = db.Column(db.Integer, primary_key=True)
    
    # Link to User model
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True) # Changed nullable to False, assume user always exists for a response
    user = db.relationship('User', backref=db.backref('responses', lazy='dynamic')) # Or lazy='select' or True

    # Remove old session_id if it exists in your version; the prompt version did not have it directly on Response but used session.sid
    # session_id = db.Column(db.String(100), nullable=True, index=True) # REMOVE IF PRESENT

    wiki_page_title = db.Column(db.String(255), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    answer_options = db.Column(db.Text, nullable=True)
    correct_answer = db.Column(db.String(10), nullable=False)
    user_answer = db.Column(db.String(10), nullable=True)
    user_confidence = db.Column(db.Integer, nullable=True)
    is_correct = db.Column(db.Boolean, nullable=True)
    brier_score = db.Column(db.Float, nullable=True)
    points_awarded = db.Column(db.Float, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    game_category = db.Column(db.String(255), nullable=True, index=True)

    def __repr__(self):
        return f'<Response id={self.id} user_id={self.user_id} correct={self.is_correct}>'