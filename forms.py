# forms.py

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, BooleanField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError, Optional
from models import User # To check if email or nickname is already taken

NICKNAME_MIN_LENGTH = 3
NICKNAME_MAX_LENGTH = 30

class RegistrationForm(FlaskForm):
    nickname = StringField('Nickname',
                           validators=[DataRequired(), Length(min=NICKNAME_MIN_LENGTH, max=NICKNAME_MAX_LENGTH)]) # Assuming NICKNAME_MIN_LENGTH and NICKNAME_MAX_LENGTH are accessible here or defined. We might need to import them or define them again if they are only in app.py
    email = StringField('Email',
                        validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8)]) # Added min length for password
    confirm_password = PasswordField('Confirm Password',
                                     validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Sign Up')

    # Custom validator to check if the nickname is already taken
    def validate_nickname(self, nickname):
        # This validator will be used if we decide to allow changing the nickname during registration,
        # or if a new user (not in nickname setup phase) registers directly.
        # For users "claiming" an existing nickname, the logic in the route will be slightly different.
        user = User.query.filter_by(nickname=nickname.data).first()
        if user:
            # We need to be careful here. If a user is in the session with this nickname
            # and is trying to register it with an email, this validation might conflict.
            # The route logic will need to handle this. For now, let's assume a general case.
            # For a truly new registration, or if the nickname in the form is different
            # from one potentially in session, this is fine.
            # We will refine this interaction in the route.
            # A simple approach might be to only apply this if no user is in session or 
            # if the nickname in form differs from session['nickname'].
            # For now, let's keep it simple.
            # If we want to allow users to register an *existing* un-emailed nickname,
            # we might skip this check if the nickname matches session['nickname']
            # and that user record doesn't yet have an email.
            #
            # Let's re-evaluate this validator's behavior once we're in the route.
            # For now, it checks general uniqueness.
            #
            # Alternative: only check if User.query.filter_by(nickname=nickname.data, email=None).first()
            # and the current session user is NOT that user. This gets complex quickly for a form validator.
            # The route is a better place for nuanced logic.
            #
            # Simplest for now: if it exists, and doesn't have an email yet, it's claimable.
            # If it exists and *has* an email, it's taken.
            existing_user = User.query.filter_by(nickname=nickname.data).first()
            if existing_user and existing_user.email: # If nickname exists AND has an email, it's truly taken.
                raise ValidationError('That nickname is already registered with an email. Please choose a different one.')
            # If it exists but no email, it's okay for now, the route will handle "claiming".

    # Custom validator to check if the email is already taken
    def validate_email(self, email):
        user = User.query.filter_by(email=email.data.lower()).first() # Store and check emails in lowercase
        if user:
            raise ValidationError('That email is already registered. Please choose a different one or log in.')

class LoginForm(FlaskForm):
    email = StringField('Email',
                        validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember Me') # Optional "Remember Me" functionality
    submit = SubmitField('Login')

class RequestResetForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Request Password Reset')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data.lower()).first()
        if user is None:
            raise ValidationError('There is no account with that email. You must register first.')

class ResetPasswordForm(FlaskForm):
    password = PasswordField('New Password', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField('Confirm New Password',
                                     validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Reset Password')

class FeedbackForm(FlaskForm):
    email = StringField('Your Email (Optional - for follow-up)', 
                        validators=[Optional(), Email(message="Please enter a valid email address.")])
    
    feedback_type = SelectField('Type of Feedback', 
                                choices=[
                                    ('', '-- Select Type --'), # Placeholder option
                                    ('bug', 'Bug Report'),
                                    ('suggestion', 'Feature Suggestion'),
                                    ('general', 'General Comment/Question')
                                ], 
                                validators=[DataRequired(message="Please select a feedback type.")])
    
    message = TextAreaField('Your Message', 
                            validators=[DataRequired(message="Please enter your feedback message."), 
                                        Length(min=10, max=5000, message="Message must be between 10 and 5000 characters.")])
    
    # Optional: If you want to ask for context directly from user
    # page_context = StringField('Page/Context (Optional - e.g., URL where issue occurred)',
    #                            validators=[Optional(), Length(max=255)])

    submit = SubmitField('Submit Feedback')