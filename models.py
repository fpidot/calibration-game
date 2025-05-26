# models.py

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from flask_login import UserMixin
from flask import current_app # To access app.config['SECRET_KEY']
from itsdangerous import URLSafeTimedSerializer as Serializer # For token generation

db = SQLAlchemy()

# --- Model Definitions ---

class User(db.Model, UserMixin): # Inherit from UserMixin
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True) # Flask-Login uses this via get_id()
    nickname = db.Column(db.String(80), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True, index=True)
    password_hash = db.Column(db.String(255), nullable=True)
    email_confirmed_at = db.Column(db.DateTime, nullable=True)
    last_login_at = db.Column(db.DateTime, nullable=True)

    def get_reset_token(self, expires_sec=1800): # Default 30 minutes expiration
        """Generates a password reset token."""
        s = Serializer(current_app.config['SECRET_KEY'])
        # We embed the user_id in the token. The serializer adds a timestamp.
        return s.dumps({'user_id': self.id})

    @staticmethod
    def verify_reset_token(token, expires_sec=1800):
        """
        Verifies a password reset token.
        Returns the User object if the token is valid and not expired, otherwise None.
        """
        s = Serializer(current_app.config['SECRET_KEY'])
        try:
            # loads() checks both the signature and the expiration time (max_age)
            data = s.loads(token, max_age=expires_sec) 
            user_id = data.get('user_id')
        except Exception as e: # Catches BadSignature, SignatureExpired, etc. from itsdangerous
            print(f"Token verification failed: {e}") # Optional: Log for debugging
            return None
        return User.query.get(user_id) # Return the user associated with the user_id in the token
    
    def __repr__(self):
        return f'<User {self.id} {self.nickname} Email: {self.email}>' # Added email to repr for clarity
    
class AppSetting(db.Model):
    """Stores application settings as key-value pairs."""
    __tablename__ = 'app_settings' # Optional: define a table name

    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    setting_value = db.Column(db.Text, nullable=True) # Use Text for potentially long values
    description = db.Column(db.String(255), nullable=True) # Optional: Add description for Admin UI

    def __repr__(self):
        return f'<AppSetting {self.setting_key}={self.setting_value[:20]}>'

class GameSummary(db.Model):
    __tablename__ = 'game_summaries'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    user = db.relationship('User', backref=db.backref('game_summaries', lazy='dynamic'))
    
    game_category = db.Column(db.String(255), nullable=True, index=True) # Same as in Response
    score = db.Column(db.Float, nullable=False)
    average_brier_score = db.Column(db.Float, nullable=True)
    questions_answered = db.Column(db.Integer, nullable=False) # Should match game_length setting at time of game
    completed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Optional: Store the game_length setting used for this game if it can vary
    # game_length_setting = db.Column(db.Integer, nullable=False)

    def __repr__(self):
        return f'<GameSummary id={self.id} user_id={self.user_id} category="{self.game_category}" score={self.score}>'

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
    
class UserFeedback(db.Model):
    __tablename__ = 'user_feedback'

    id = db.Column(db.Integer, primary_key=True)
    
    # Link to User model (nullable if guests can submit feedback)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    user = db.relationship('User', backref=db.backref('feedbacks', lazy='dynamic'))

    # Information captured at submission time
    # For guests, or if a logged-in user wants to provide a different contact
    email_address_at_submission = db.Column(db.String(120), nullable=True) 
    # For guests who provide a nickname, or the logged-in user's nickname at the time
    nickname_at_submission = db.Column(db.String(80), nullable=True) 

    feedback_type = db.Column(db.String(50), nullable=True) # e.g., "Bug", "Suggestion", "General"
    message = db.Column(db.Text, nullable=False) # The actual feedback content
    
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Optional context information
    user_agent_string = db.Column(db.String(255), nullable=True) # From request.user_agent.string
    page_context = db.Column(db.String(255), nullable=True) # e.g., URL or section where feedback was initiated
    
    # Optional: For tracking if feedback has been addressed by an admin
    is_resolved = db.Column(db.Boolean, default=False, nullable=False)
    admin_notes = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<UserFeedback id={self.id} user_id={self.user_id or "Guest"} type="{self.feedback_type}">'