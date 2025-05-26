import os
import random
import re 
import requests
import math
from flask import Flask, render_template, request, jsonify, session, flash, redirect, url_for
from flask_migrate import Migrate
from flask_admin import Admin
from flask_bootstrap import Bootstrap # Make sure this is initialized only once too
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from dotenv import load_dotenv
import google.generativeai as genai
import wikipediaapi
from sqlalchemy.exc import IntegrityError
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from forms import RegistrationForm, LoginForm, FeedbackForm, RequestResetForm, ResetPasswordForm
from models import db, User, Response, AppSetting, GameSummary, UserFeedback
from datetime import datetime
from sqlalchemy import desc, asc, func, case, literal_column

# --- App Configuration ---
load_dotenv()
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')

@app.context_processor
def utility_processor():
    return dict(get_setting=get_setting)

@app.context_processor
def inject_current_year():
    return {'current_year': datetime.utcnow().year}

# --- Initialize Extensions (do this ONCE for each) ---
bootstrap = Bootstrap(app) # Initialize Bootstrap
db.init_app(app)           # Initialize SQLAlchemy with the app
migrate = Migrate(app, db) # Initialize Migrate

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'
login_manager.session_protection = "strong"

# --- Admin Setup (Initialize Admin ONCE and add views) ---
from admin_views import AppSettingAdminView, ResponseAdminView, UserAdminView, UserFeedbackAdminView
admin = Admin(app, name='Trivia Admin', template_mode='bootstrap3')
admin.add_view(AppSettingAdminView(AppSetting, db.session))
admin.add_view(ResponseAdminView(Response, db.session))
admin.add_view(UserAdminView(User, db.session)) 
admin.add_view(UserFeedbackAdminView(UserFeedback, db.session))

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # The name of your login route's view function
login_manager.login_message_category = 'info' # Category for flash messages
login_manager.session_protection = "strong" # Or "basic" or None


# --- API Setups ---
wiki_user_agent_contact = os.getenv('WIKI_USER_AGENT_CONTACT', 'your_email@example.com')
WIKI_USER_AGENT = f'WikipediaTriviaGame/1.0 (https://github.com/fpidot/calibration-game; {wiki_user_agent_contact})'
wiki_wiki = wikipediaapi.Wikipedia(user_agent=WIKI_USER_AGENT, language='en')

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
gemini_model = None 
if not GEMINI_API_KEY: print("Warning: GEMINI_API_KEY not set. Question generation and category standardization disabled.")
else:
    try: 
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model = genai.GenerativeModel('gemini-1.5-flash') 
        print("Gemini API configured.")
    except Exception as e: 
        print(f"Error configuring Gemini API: {e}.")
        gemini_model = None

# --- Constants ---
PAGE_FETCH_ATTEMPTS = 5 
WIKI_SEARCH_LIMIT_PER_THEME = 10 
MAX_GENERATION_ATTEMPTS = 3
NICKNAME_MAX_LENGTH = 30
NICKNAME_MIN_LENGTH = 3
NICKNAME_REGEX = re.compile(r"^[a-zA-Z0-9_]+$") 

# --- Nickname Generation Data ---
ADJECTIVES = [
    "Quick", "Happy", "Clever", "Silent", "Witty", "Brave", "Calm", "Eager", 
    "Gentle", "Jolly", "Kind", "Lively", "Proud", "Silly", "Wild", "Zealous",
    "Azure", "Golden", "Crimson", "Emerald", "Cosmic", "Quantum"
]
NOUNS = [
    "Fox", "Lion", "Hawk", "Puma", "Wolf", "Bear", "Eagle", "Shark", 
    "Tiger", "Jaguar", "Panther", "Sprite", "Drake", "Sphinx", "Griffin",
    "Robot", "Ninja", "Wizard", "Planet", "Star", "Nebula", "Quasar"
]

# --- Helper Functions ---
@login_manager.user_loader
def load_user(user_id):
    # user_id is a string, convert to int for querying
    return User.query.get(int(user_id))

def send_reset_email(user_for_reset):
    """
    Generates a password reset token for the user and simulates sending an email
    by printing the reset link to the console.
    In a production app, this would use Flask-Mail or a similar library.
    """
    token = user_for_reset.get_reset_token() # Assumes get_reset_token is a method on your User model
    
    # _external=True is important for generating a full URL including the domain,
    # which is needed for links in emails (even simulated ones).
    reset_url = url_for('reset_token', token=token, _external=True) 
    
    print("---- PASSWORD RESET EMAIL (SIMULATED) ----")
    print(f"To: {user_for_reset.email}")
    print(f"Subject: Password Reset Request - Wikipedia Calibration Game")
    print(f"Body: To reset your password for the Wikipedia Calibration Game, please visit the following link within 30 minutes:")
    print(reset_url)
    print("If you did not request this, please ignore this message.")
    print("-------------------------------------------")
    #
    # Example for actual email sending with Flask-Mail (if you configure it later):
    # from flask_mail import Message
    # from app import mail # Assuming 'mail = Mail(app)' is configured
    #
    # msg = Message('Password Reset Request - Wikipedia Calibration Game',
    #               sender=current_app.config.get('MAIL_DEFAULT_SENDER', 'noreply@example.com'), # Use a config var
    #               recipients=[user_for_reset.email])
    # msg.body = f'''To reset your password, visit the following link:
    # {reset_url}

    # This link will expire in 30 minutes.

    # If you did not make this request then simply ignore this email and no changes will be made.
    # '''
    # try:
    #     mail.send(msg)
    #     print(f"Password reset email ostensibly sent to {user_for_reset.email}")
    # except Exception as e:
    #     print(f"Error sending password reset email: {e}") # Log error

def get_setting(key, default_value):
    setting = AppSetting.query.filter_by(setting_key=key).first()
    if setting and setting.setting_value is not None:
        try:
            value_type = type(default_value)
            if value_type is bool:
                val = setting.setting_value.lower().strip()
                if val in ('true', '1'): return True
                elif val in ('false', '0'): return False
                return default_value
            if key in ['user_selectable_categories', 'search_keywords', 'target_categories'] and value_type is str:
                 return setting.setting_value 
            return value_type(setting.setting_value)
        except (ValueError, TypeError): return default_value
    return default_value

def get_standardized_category_via_gemini(custom_text: str) -> str:
    if not gemini_model:
        print("Gemini model not available for category standardization. Returning original text.")
        return custom_text 
    prompt = f"""Given the user's topic query: '{custom_text}', suggest a concise and effective search term or a thematic category name that best represents this query for finding relevant Wikipedia articles. The output should be suitable for a Wikipedia search. Return *only* the suggested term/category name, without any preamble or explanation. For example, if the input is 'dinosaurs from cretaceous', a good output might be 'Cretaceous period dinosaurs' or 'Dinosaurs of the Cretaceous period'. If the input is already a good search term like 'Quantum Physics', return it as is or make minimal refinements if necessary.
User topic query: '{custom_text}'
Suggested search term/thematic category name:"""
    try:
        print(f"Standardizing custom category with Gemini. Input: '{custom_text}'")
        response = gemini_model.generate_content(prompt)
        standardized_term = response.text.strip()
        if not standardized_term:
            print("Gemini returned empty for category standardization. Falling back to original.")
            return custom_text
        print(f"Gemini standardized '{custom_text}' to '{standardized_term}'")
        return standardized_term
    except Exception as e:
        print(f"Error during Gemini category standardization: {e}. Falling back to original text.")
        return custom_text

def generate_suggested_nickname():
    max_attempts = 20 
    for _ in range(max_attempts):
        adj = random.choice(ADJECTIVES); noun = random.choice(NOUNS); num = random.randint(1, 999)
        nickname = f"{adj}{noun}{num}"
        # Light check, actual uniqueness enforced at /set_nickname
        if not User.query.filter_by(nickname=nickname).first(): 
            return nickname
    return f"{random.choice(ADJECTIVES)}{random.choice(NOUNS)}{random.randint(1,999)}" # Fallback

def ensure_user_session_initialized():
    if current_user.is_authenticated: # Fully logged-in user
        if session.get('needs_nickname_setup'): # Cleanup
            session.pop('needs_nickname_setup', None)
            session.pop('suggested_nickname', None)
            session.modified = True
        return current_user

    # Check for "nickname-only" user (has session user_id from /set_nickname but not Flask-Login authenticated)
    if session.get('user_id') and session.get('nickname'):
        # This user has completed /set_nickname. They don't need nickname setup UI.
        # We don't return a User object here because they aren't "authenticated" in Flask-Login sense.
        # The index route will use session data to identify them.
        if session.get('needs_nickname_setup'): # Cleanup if this flag is somehow still set
            session.pop('needs_nickname_setup', None)
            session.pop('suggested_nickname', None)
            session.modified = True
        return None # Indicate not Flask-Login authenticated, but index route will handle via session

    # If not Flask-Login authenticated AND no user_id/nickname in session, then it's a new guest.
    if not session.get('needs_nickname_setup'):
        print("ensure_user_session_initialized: New guest. Initiating nickname setup phase.")
        suggested_nick = generate_suggested_nickname()
        session['needs_nickname_setup'] = True
        session['suggested_nickname'] = suggested_nick
        session.modified = True
    
    return None # Guest in setup

def nickname_setup_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Case 1: User is authenticated via Flask-Login (email/password).
        # They inherently have a nickname and user ID.
        if current_user.is_authenticated:
            return f(current_user, *args, **kwargs) # Pass the Flask-Login current_user object

        # Case 2: User is NOT authenticated via Flask-Login.
        # We now check our "old" session-based nickname setup.
        # This caters to users who might have only completed the /set_nickname step
        # and haven't fully registered with email/password, or for any other non-Flask-Login managed user state.

        if session.get('needs_nickname_setup'):
            # If they are still in the explicit "needs_nickname_setup" phase, block access.
            return jsonify({"error": "Nickname setup required.", "action_needed": "complete_nickname_setup"}), 403
        
        user_id_in_session = session.get('user_id')
        nickname_in_session = session.get('nickname')

        if not user_id_in_session or not nickname_in_session:
            # If they don't have user_id/nickname in session AND are not in 'needs_nickname_setup',
            # something is amiss or it's a new guest hitting a protected route. Force setup.
            print("Decorator: User ID or Nickname missing from session (and not Flask-Login auth'd), forcing setup.")
            session['needs_nickname_setup'] = True # Trigger nickname setup UI on next page load (e.g., index)
            session['suggested_nickname'] = generate_suggested_nickname()
            session.modified = True
            return jsonify({"error": "User session incomplete. Please set nickname first.", "action_needed": "complete_nickname_setup"}), 403
        
        # If user_id and nickname are in session (from /set_nickname), load this "nickname-only" user.
        user = User.query.get(int(user_id_in_session)) # Ensure user_id is int if needed

        if not user or user.nickname != nickname_in_session: 
            # If user_id in session doesn't match DB or nickname mismatch, the session is invalid.
            print(f"Decorator: Nickname-only user session invalid (ID: {user_id_in_session}, Nick: {nickname_in_session}, DB User: {user}). Forcing re-setup.")
            session.clear() # Clear the potentially corrupt session.
            session['needs_nickname_setup'] = True # Force a full fresh start.
            session['suggested_nickname'] = generate_suggested_nickname()
            session.modified = True
            return jsonify({"error": "User session invalid. Please complete nickname setup again.", "action_needed": "complete_nickname_setup"}), 403
        
        # If we reach here, it's a valid "nickname-only" user (from /set_nickname).
        return f(user, *args, **kwargs) # Pass the manually loaded User object
    return decorated_function

def get_wikipedia_page(
    admin_page_selection_strategy: str, 
    admin_search_keywords: str, 
    admin_target_categories: str, 
    admin_api_result_limit: int,
    user_category_theme: str = None 
    ):
    page_candidates = []; min_summary_words_check = get_setting('min_summary_words', 50); headers = {'User-Agent': WIKI_USER_AGENT}
    
    if user_category_theme:
        print(f"Attempting to find page for user category theme: '{user_category_theme}'")
        try:
            S = requests.Session(); URL = "https://en.wikipedia.org/w/api.php"; PARAMS = {"action": "query", "format": "json", "list": "search", "srsearch": user_category_theme, "srnamespace": "0", "srlimit": str(WIKI_SEARCH_LIMIT_PER_THEME), "srwhat": "text", "srqiprofile": "classic_noboostlinks", "srsort": "relevance"}
            R = S.get(url=URL, params=PARAMS, headers=headers); R.raise_for_status(); data = R.json(); search_results = data.get("query", {}).get("search", [])
            if search_results: page_candidates = [result['title'] for result in search_results]; print(f"Found {len(page_candidates)} candidates for theme '{user_category_theme}': {page_candidates[:5]}")
            else: print(f"No Wikipedia search results for user theme '{user_category_theme}'.")
        except requests.exceptions.RequestException as e: print(f"Network error searching for user theme '{user_category_theme}': {e}")
        except Exception as e: print(f"Unexpected error searching for user theme '{user_category_theme}': {e}")
    else: 
        print(f"Using admin strategy: '{admin_page_selection_strategy}'"); current_strategy = admin_page_selection_strategy
        if current_strategy == 'search':
            keywords = [k.strip() for k in admin_search_keywords.split(',') if k.strip()];
            if keywords:
                keyword = random.choice(keywords); print(f"Admin search: '{keyword}'")
                try: 
                    S = requests.Session(); URL = "https://en.wikipedia.org/w/api.php"; PARAMS = {"action": "query","format": "json","list": "search","srsearch": keyword,"srnamespace": "0","srlimit": str(admin_api_result_limit),"srwhat": "text"}
                    R = S.get(url=URL, params=PARAMS, headers=headers); R.raise_for_status(); data = R.json(); search_results = data.get("query", {}).get("search", [])
                    if search_results: page_candidates = [r['title'] for r in search_results]
                except Exception as e: print(f"Error in admin search for '{keyword}': {e}")
            else: current_strategy = 'random' 
        
        # Use 'if' instead of 'elif' to allow fallback from empty search keywords to category, then to random
        if current_strategy == 'category': 
            categories = [c.strip() for c in admin_target_categories.split(',') if c.strip()]
            if categories:
                category_name_base = random.choice(categories); category_name = category_name_base if category_name_base.lower().startswith("category:") else f"Category:{category_name_base}"; print(f"Admin category: '{category_name}'")
                try: 
                    S = requests.Session(); URL = "https://en.wikipedia.org/w/api.php"; PARAMS = {"action": "query","format": "json","list": "categorymembers","cmtitle": category_name,"cmlimit": str(admin_api_result_limit),"cmtype": "page","cmprop": "title"}
                    R = S.get(url=URL, params=PARAMS, headers=headers); R.raise_for_status(); data = R.json(); members = data.get("query", {}).get("categorymembers", [])
                    if members: page_candidates = [m['title'] for m in members]
                except Exception as e: print(f"Error in admin category '{category_name}': {e}")
            else: current_strategy = 'random'
        
        if current_strategy == 'random' or not page_candidates: 
            print("Using admin random strategy or fallback.");
            try: 
                S = requests.Session(); URL = "https://en.wikipedia.org/w/api.php"; PARAMS = {"action": "query","format": "json","list": "random","rnnamespace": "0","rnlimit": str(admin_api_result_limit)}
                R = S.get(url=URL, params=PARAMS, headers=headers); R.raise_for_status(); data = R.json(); random_pages = data.get("query", {}).get("random", [])
                if random_pages: page_candidates.extend([p["title"] for p in random_pages if p["title"] not in page_candidates]) 
            except Exception as e: print(f"Error in admin random: {e}")

    if not page_candidates:
        print("No page candidates found from any strategy.");
        if not user_category_theme: 
            print("Final fallback to single random page.");
            try: 
                S = requests.Session(); URL = "https://en.wikipedia.org/w/api.php"; PARAMS = {"action": "query","format": "json","list": "random","rnnamespace": "0","rnlimit": "1"}
                R = S.get(url=URL, params=PARAMS, headers=headers); R.raise_for_status(); data = R.json(); random_page_data = data.get("query", {}).get("random", [])
                if random_page_data: page_candidates = [random_page_data[0]["title"]]
            except Exception as e: print(f"Error in final fallback random: {e}")
        if not page_candidates: return None

    random.shuffle(page_candidates); attempts = 0
    for title_to_check in page_candidates:
        if attempts >= PAGE_FETCH_ATTEMPTS: break; attempts += 1
        print(f"Validation Attempt {attempts}/{len(page_candidates)} for title: '{title_to_check}'")
        try:
            page = wiki_wiki.page(title_to_check)
            if page and page.exists():
                summary_lower = page.summary.lower();
                if "may refer to:" in summary_lower or page.title.lower().endswith("(disambiguation)") or "is a disambiguation page" in summary_lower: print(f"'{page.title}' is a disambiguation page. Skipping."); continue
                if len(page.summary.split()) < max(10, min_summary_words_check // 2) and len(page.sections) <=1 : print(f"'{page.title}' appears to be a stub. Skipping."); continue
                print(f"Validated page: {page.title}"); return page
            else: print(f"Page '{title_to_check}' not found or does not exist. Skipping.")
        except Exception as e: print(f"Error validating page '{title_to_check}': {e}. Skipping."); continue
    print(f"Failed to find and validate a suitable page after {attempts} attempts."); return None

def generate_question_from_text(text, context_length, game_theme=None):
    if not text: print("Error: Empty text for Q gen."); return None,None,None
    if not gemini_model: print("Error: Gemini model unavailable for Q gen."); return None,None,None
    theme_context = f"The trivia question should ideally be related to the overall game theme of '{game_theme}'. " if game_theme else ""
    text_to_send = text[:context_length]
    prompt = f"""{theme_context}Create a multiple-choice trivia question based *only* on the following text. The question should be specific, but answerable by a reasonably well educated adult with at least a little knowledge of the topic. The question itself should never refer to "the text" or "the article" or "the provided document" (e.g., avoid starting with "According to the text..."). Provide the question, 4 distinct answer choices (A, B, C, D) where only one is correct according to the text, and indicate the correct answer letter. Format the output *exactly* like this, with each part on a new line:\n\nQuestion: [Your question here]\nA) [Choice A]\nB) [Choice B]\nC) [Choice C]\nD) [Choice D]\nCorrect Answer: [Correct Letter (A, B, C, or D)]\n\nText:\n{text_to_send}"""
    try:
        response = gemini_model.generate_content(prompt); content = response.text.strip(); lines = [line.strip() for line in content.split('\n') if line.strip()]; question = None; options = {}; correct_answer_letter = None
        if not lines or not lines[0].startswith("Question:"): print(f"Parsing Error: No 'Question:'. Line: '{lines[0] if lines else 'N/A'}'"); return None,None,None
        question = lines[0][len("Question:"):].strip(); option_prefixes = ['A)', 'B)', 'C)', 'D)']; temp_options = {}; option_lines_found = 0; current_line_index = 1
        while option_lines_found < 4 and current_line_index < len(lines):
             line = lines[current_line_index]; expected_prefix = option_prefixes[option_lines_found]
             if line.startswith(expected_prefix): temp_options[expected_prefix[0]] = line[len(expected_prefix):].strip(); option_lines_found += 1
             current_line_index += 1
        if option_lines_found == 4: options = temp_options
        else: print(f"Parsing Error: Found {option_lines_found}/4 options. Lines: {lines}"); return None,None,None
        found_correct_line = False
        while current_line_index < len(lines):
            line = lines[current_line_index]
            if line.startswith("Correct Answer:"):
                correct_answer_letter = line[len("Correct Answer:"):].strip().upper()
                if correct_answer_letter not in options: print(f"Parsing Error: Correct letter '{correct_answer_letter}' not in options."); correct_answer_letter = None
                found_correct_line = True; break
            current_line_index += 1
        if not found_correct_line or not correct_answer_letter: print(f"Parsing Error: No 'Correct Answer:' or invalid. Lines: {lines}"); return None,None,None
        print(f"Successfully parsed Gemini response for Q&A. Theme context used: '{game_theme if game_theme else 'None'}'"); return question, options, correct_answer_letter
    except Exception as e: print(f"Error in Gemini Q gen (theme: {game_theme}): {e}"); return None,None,None

def calculate_brier_score(confidence, is_correct):
    probability = confidence / 100.0; outcome = 1.0 if is_correct else 0.0
    return (probability - outcome)**2

def initialize_session_stats(force_reset=False): # Added force_reset parameter
    default_stats = {
        'total_answered': 0, 
        'total_correct': 0, 
        'brier_scores': [],             # Overall session brier scores
        'game_brier_scores': [],        # Brier scores for the current game
        'confidence_levels': [], 
        'correctness': [], 
        'cumulative_score': 0.0,        # Current game's score
        'questions_this_game': 0,       # Questions in current game
        'games_played_session': 0,      # Number of "games" (as defined by game_length) completed in session
        'completed_game_scores_session': [], # Scores of completed games in this session
        'current_game_category': None 
    }
    if force_reset or 'stats' not in session: # If forcing reset or stats don't exist
        session['stats'] = default_stats.copy()
        if force_reset:
            print("Session stats force reset.")
        else:
            print("New session or no stats: Initialized all stats.")
    else: # Stats exist, ensure all keys are present (for backward compatibility or partial resets)
        updated = False
        for key, default_val in default_stats.items():
            if key not in session['stats']:
                session['stats'][key] = default_val
                updated = True
        if updated:
            print("Existing session stats: Ensured all stat keys are present.")
    session.modified = True
    return session['stats'] # Return the stats dict for convenience

# --- Routes ---

@app.route('/')
def index():
    user_object_from_session_init = ensure_user_session_initialized() 
    current_session_stats = initialize_session_stats()
    active_question_data = session.get('current_question') 
    last_answer_feedback_data = session.get('last_answer_feedback') # Get feedback if it exists

    # If there's feedback, there shouldn't be an active question for a new turn yet.
    # And if there's an active question, there shouldn't be lingering feedback.
    # current_question takes precedence if both somehow exist.
    if active_question_data:
        if last_answer_feedback_data: # Unlikely state, but clear feedback if new question is up
            session.pop('last_answer_feedback', None)
            last_answer_feedback_data = None
            session.modified = True
    
    category_stats = []
    overall_lifetime_stats = None # Initialize
    best_brier_category = None
    worst_brier_category = None
    best_score_category = None
    worst_score_category = None
    personal_best_game_score_data = None
    personal_best_game_brier_data = None

    if current_user.is_authenticated:
        # --- Fetch Overall Lifetime Stats for logged-in user ---
        overall_stats_query = db.session.query(
            func.count(Response.id).label('total_questions_lifetime'),
            func.sum(case((Response.is_correct == True, 1), else_=0)).label('total_correct_lifetime'),
            func.avg(Response.brier_score).label('average_brier_lifetime'),
            func.sum(Response.points_awarded).label('total_points_lifetime')
        ).filter(Response.user_id == current_user.id).first()
        
        if overall_stats_query and overall_stats_query.total_questions_lifetime is not None: # Check if any responses exist
            accuracy = (overall_stats_query.total_correct_lifetime / overall_stats_query.total_questions_lifetime * 100) \
                        if overall_stats_query.total_questions_lifetime > 0 else 0
            overall_lifetime_stats = {
                'total_questions': overall_stats_query.total_questions_lifetime,
                'total_correct': overall_stats_query.total_correct_lifetime or 0, # Ensure 0 if None
                'accuracy': round(accuracy, 1),
                'average_brier': round(overall_stats_query.average_brier_lifetime, 3) \
                                 if overall_stats_query.average_brier_lifetime is not None else None,
                'total_points': round(overall_stats_query.total_points_lifetime, 1) \
                                if overall_stats_query.total_points_lifetime is not None else 0
            }
        else: # No responses yet for this user
            overall_lifetime_stats = {
                'total_questions': 0, 'total_correct': 0, 'accuracy': 0,
                'average_brier': None, 'total_points': 0
            }

        # --- Fetch Category-Specific Lifetime Stats (existing logic) ---
        user_category_data = db.session.query(
            Response.game_category.label('display_category_name'),
            func.count(Response.id).label('total_questions'),
            func.sum(case((Response.is_correct == True, 1), else_=0)).label('total_correct'),
            func.avg(Response.brier_score).label('average_brier'),
            func.avg(Response.points_awarded).label('average_points')
        ).filter(Response.user_id == current_user.id)\
         .group_by(Response.game_category)\
         .order_by(Response.game_category)\
         .all()

        for cat_data in user_category_data:
            cat_accuracy = (cat_data.total_correct / cat_data.total_questions * 100) if cat_data.total_questions > 0 else 0
            category_stats.append({
                'category_name': cat_data.display_category_name,
                'total_questions': cat_data.total_questions,
                'total_correct': cat_data.total_correct,
                'accuracy': round(cat_accuracy, 1),
                'average_brier': round(cat_data.average_brier, 3) if cat_data.average_brier is not None else None,
                'average_points': round(cat_data.average_points, 1) if cat_data.average_points is not None else None
            })

        # --- Calculate Best/Worst Categories ONLY if category_stats were populated ---
        if category_stats:
            # Fetch MIN_QUESTIONS_FOR_CATEGORY_RANKING setting
            # It's better to fetch settings once if used multiple times or ensure get_setting is efficient
            min_questions_setting_val_str = AppSetting.query.filter_by(setting_key='min_questions_for_cat_rank').first()
            MIN_QUESTIONS_FOR_CATEGORY_RANKING = 5 # Default
            if min_questions_setting_val_str and min_questions_setting_val_str.setting_value:
                try:
                    MIN_QUESTIONS_FOR_CATEGORY_RANKING = int(min_questions_setting_val_str.setting_value)
                except ValueError:
                    print("Warning: Could not parse 'min_questions_for_cat_rank' from AppSetting, using fallback 5.")
            
            rankable_brier_categories = [
                s for s in category_stats 
                if s['total_questions'] >= MIN_QUESTIONS_FOR_CATEGORY_RANKING and s.get('average_brier') is not None
            ]
            if rankable_brier_categories:
                best_brier_category = min(rankable_brier_categories, key=lambda x: x['average_brier'])
                worst_brier_category = max(rankable_brier_categories, key=lambda x: x['average_brier'])

            rankable_score_categories = [
                s for s in category_stats 
                if s['total_questions'] >= MIN_QUESTIONS_FOR_CATEGORY_RANKING and s.get('average_points') is not None
            ]
            if rankable_score_categories:
                best_score_category = max(rankable_score_categories, key=lambda x: x['average_points'])
                worst_score_category = min(rankable_score_categories, key=lambda x: x['average_points'])

        best_score_game_summary = GameSummary.query\
            .filter_by(user_id=current_user.id)\
            .order_by(GameSummary.score.desc())\
            .first()
        if best_score_game_summary:
            personal_best_game_score_data = { # Use the renamed variable
                'score': best_score_game_summary.score,
                'category': best_score_game_summary.game_category or "General Knowledge",
                'date': best_score_game_summary.completed_at
            }

        # Lowest Single Game Average Brier
        best_brier_game_summary = GameSummary.query\
            .filter(GameSummary.user_id == current_user.id, GameSummary.average_brier_score.isnot(None))\
            .order_by(GameSummary.average_brier_score.asc())\
            .first()
        if best_brier_game_summary:
            personal_best_game_brier_data = { # Use the renamed variable
                'brier': best_brier_game_summary.average_brier_score,
                'category': best_brier_game_summary.game_category or "General Knowledge",
                'date': best_brier_game_summary.completed_at,
                'score_in_that_game': best_brier_game_summary.score
            }

    # --- Prepare template_vars ---
    template_vars = {
        'active_question_data': active_question_data,
        'last_answer_feedback_data': last_answer_feedback_data,
        'user_info': None,
        'needs_nickname_setup': False, 
        'suggested_nickname': None, # Will be populated below if needed
        
        'category_stats': category_stats, # Lifetime category stats for logged-in users
        'overall_lifetime_stats': overall_lifetime_stats, # NEW: Overall lifetime stats for logged-in
        'session_stats_for_guest': None, # Will be populated for guests
        

        # Best/Worst category stats (ensure these are added from your existing logic)
        'best_brier_category': best_brier_category,
        'worst_brier_category': worst_brier_category,
        'best_score_category': best_score_category,
        'worst_score_category': worst_score_category,

        'personal_best_game_score': personal_best_game_score_data,
        'personal_best_game_brier': personal_best_game_brier_data
    }
    
    template_vars['default_chart_bins'] = int(get_setting('calibration_chart_bins', 10))

    if current_user.is_authenticated:
        template_vars['user_info'] = {
            'nickname': current_user.nickname, 
            'user_id': current_user.id, 
            'email_registered': True 
        }
        # For logged-in users, 'session_stats_for_guest' remains None.
        # The 'current game progress X/Y' and 'current game score' from session
        # can still be displayed if desired, separate from lifetime stats.
        # We can pass current_session_stats if we want to show current game progress.
        template_vars['current_game_progress_stats'] = {
            'questions_this_game': current_session_stats.get('questions_this_game', 0),
            'game_length_setting': int(get_setting('game_length', 20)),
            'current_game_score': current_session_stats.get('cumulative_score', 0.0)
        }

    elif session.get('user_id') and session.get('nickname'): # Nickname-only user
        template_vars['user_info'] = { 
            'nickname': session.get('nickname'), 
            'user_id': session.get('user_id'), 
            'email_registered': False
        }
        # Nickname-only users are treated like guests for stats display (session-based)
        template_vars['session_stats_for_guest'] = current_session_stats
    else: # New guest
        template_vars['needs_nickname_setup'] = session.get('needs_nickname_setup', True) 
        template_vars['user_info'] = None
        template_vars['session_stats_for_guest'] = current_session_stats
        if template_vars['needs_nickname_setup']:
            template_vars['suggested_nickname'] = session.get('suggested_nickname')

    if not template_vars['needs_nickname_setup']:
        template_vars['suggested_nickname'] = None

    return render_template('index.html', **template_vars)

@app.route("/reset_password_request", methods=['GET', 'POST']) # Renamed for clarity from just /reset_password
def reset_request():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RequestResetForm()
    if form.validate_on_submit():
        user_to_reset = User.query.filter_by(email=form.email.data.lower()).first()
        # The form's validate_email already checks if the user exists.
        # If it passes, user_to_reset will be a User object.
        if user_to_reset:
            send_reset_email(user_to_reset) # This calls your function that prints to console
            flash('If an account with that email exists, instructions to reset your password have been sent (check your console).', 'info')
        else:
            # This case should ideally not be reached if the form validator works,
            # but as a fallback or if you change the validator behavior.
            flash('No account found with that email address.', 'warning') 
        return redirect(url_for('login')) # Always redirect to login to not reveal if email exists
    return render_template('reset_request.html', title='Request Password Reset', form=form)


@app.route("/reset_password/<token>", methods=['GET', 'POST'])
def reset_token(token):
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    user_to_reset = User.verify_reset_token(token) # Use the static method from User model
    
    if user_to_reset is None:
        flash('That is an invalid or expired password reset token. Please request a new one.', 'warning')
        return redirect(url_for('reset_request')) # Redirect to the request form
    
    form = ResetPasswordForm()
    if form.validate_on_submit():
        hashed_password = generate_password_hash(form.password.data)
        user_to_reset.password_hash = hashed_password
        db.session.commit()
        flash('Your password has been successfully updated! You can now log in with your new password.', 'success')
        return redirect(url_for('login'))
        
    return render_template('reset_token.html', title='Reset Your Password', form=form, token=token)

@app.route('/leaderboard/category/<path:category_name>')
def leaderboard_category(category_name):
    # Handle the "General Knowledge" case if it might be passed as None from certain DB queries
    # or if the URL might try to represent it differently.
    # For querying the DB, if "General Knowledge" is stored as NULL in GameSummary,
    # we need to filter for NULL. If it's stored as the string "General Knowledge", filter for that.
    db_filter_value = category_name
    # db_category_filter_gs = None if category_name == "General Knowledge" else category_name
    # For Response table, we used coalesce, so the category name will be "General Knowledge" string.

    try:
        top_n = int(get_setting('leaderboard_top_n_users', 25))
        # Min games a user must have played *in this category* to be ranked for Brier/Accuracy within it
        min_games_in_category_for_ranking = int(get_setting('leaderboard_min_games_for_category_ranking', 3))
        game_length_setting = int(get_setting('game_length', 20))
        min_questions_in_category_for_ranking = min_games_in_category_for_ranking * game_length_setting
    except ValueError:
        top_n = 25
        min_games_in_category_for_ranking = 3
        min_questions_in_category_for_ranking = 3 * 20
        # flash("Warning: Could not parse category leaderboard settings, using defaults.", "warning") # Flashing here might be tricky for AJAX

    # --- Metrics for the selected category ---

    # 1. Top Game Scores in this Category (from GameSummary)
    cat_top_game_scores = db.session.query(
        User.nickname,
        GameSummary.score.label('game_score'),
        GameSummary.completed_at
    ).join(User, User.id == GameSummary.user_id)\
     .filter(GameSummary.game_category == db_filter_value)\
     .order_by(desc('game_score'))\
     .limit(top_n).all()

    # 2. Best Game Brier in this Category (from GameSummary)
    #    Users ranked here must have at least 'min_games_in_category_for_ranking' in THIS category.
    #    This subquery counts games per user in this category.
    subquery_games_in_cat = db.session.query(
        GameSummary.user_id,
        func.count(GameSummary.id).label('num_games_in_cat')
    ).filter(GameSummary.game_category == db_filter_value)\
     .group_by(GameSummary.user_id).subquery()

    cat_best_game_briers = db.session.query(
        User.nickname,
        func.avg(GameSummary.average_brier_score).label('avg_game_brier_in_cat'), # Avg of their game briers in this cat
        subquery_games_in_cat.c.num_games_in_cat
    ).join(User, User.id == GameSummary.user_id)\
     .join(subquery_games_in_cat, User.id == subquery_games_in_cat.c.user_id)\
     .filter(GameSummary.game_category == db_filter_value)\
     .filter(GameSummary.average_brier_score.isnot(None))\
     .group_by(User.id, User.nickname, subquery_games_in_cat.c.num_games_in_cat)\
     .having(subquery_games_in_cat.c.num_games_in_cat >= min_games_in_category_for_ranking)\
     .order_by(asc('avg_game_brier_in_cat'))\
     .limit(top_n).all()

    # 3. Highest Accuracy in this Category (from Response table)
    #    Users ranked here must have at least 'min_questions_in_category_for_ranking' in THIS category.
    cat_top_accuracy = db.session.query(
        User.nickname,
        (func.sum(case((Response.is_correct == True, 1), else_=0)) * 100.0 / func.count(Response.id)).label('accuracy_in_cat'),
        func.count(Response.id).label('questions_in_cat')
    ).join(Response, User.id == Response.user_id)\
     .filter(Response.game_category == db_filter_value)\
     .group_by(User.id, User.nickname)\
     .having(func.count(Response.id) >= min_questions_in_category_for_ranking)\
     .order_by(desc('accuracy_in_cat'))\
     .limit(top_n).all()
    
    # The category_name passed in the URL is used for display.
    # If category_name was "General Knowledge", db_category_filter_gs might be None.
    # So, for display, always use the category_name from the URL.
    display_category_name = category_name 

    return render_template('_leaderboard_category_content.html', 
                           category_name_display=display_category_name,
                           cat_top_game_scores=cat_top_game_scores,
                           cat_best_game_briers=cat_best_game_briers,
                           cat_top_accuracy=cat_top_accuracy,
                           get_setting=get_setting # Pass for template if it needs settings
                          )

@app.route('/leaderboard')
def leaderboard():
    try:
        top_n = int(get_setting('leaderboard_top_n_users', 25))
        # For lifetime stats from RESPONSES, we'll use a min number of total questions.
        # Let's approximate min_games * typical_game_length for this.
        min_games_for_lifetime_response_ranking_setting = int(get_setting('leaderboard_min_games_for_lifetime_ranking', 3))
        game_length_setting = int(get_setting('game_length', 20))
        min_total_questions_for_ranking = min_games_for_lifetime_response_ranking_setting * game_length_setting
        
        min_games_for_cat_lb_display = int(get_setting('leaderboard_min_games_for_category_leaderboard', 1))

    except ValueError: # Fallback if settings are not proper integers
        top_n = 25
        min_total_questions_for_ranking = 3 * 20 
        min_games_for_cat_lb_display = 1
        flash("Warning: Could not parse leaderboard settings, using defaults.", "warning")

    # --- 1. Overall Top Lifetime Scores (from Response table) ---
    top_lifetime_scores = db.session.query(
        User.nickname,
        func.sum(Response.points_awarded).label('total_score_val'), # Renamed to avoid conflict if 'total_score' is a column
        func.count(Response.id).label('total_questions_answered')
    ).join(Response, User.id == Response.user_id)\
     .group_by(User.id, User.nickname)\
     .order_by(desc('total_score_val'))\
     .limit(top_n).all()

    # --- 2. Overall Top Lifetime Accuracy (from Response table) ---
    top_lifetime_accuracy = db.session.query(
        User.nickname,
        (func.sum(case((Response.is_correct == True, 1), else_=0)) * 100.0 / func.count(Response.id)).label('accuracy_val'),
        func.count(Response.id).label('total_questions_answered')
    ).join(Response, User.id == Response.user_id)\
     .group_by(User.id, User.nickname)\
     .having(func.count(Response.id) >= min_total_questions_for_ranking)\
     .order_by(desc('accuracy_val'))\
     .limit(top_n).all()

    # --- 3. Overall Best Lifetime Calibration (Avg. Brier from Response table) ---
    top_lifetime_brier = db.session.query(
        User.nickname,
        func.avg(Response.brier_score).label('average_brier_val'),
        func.count(Response.id).label('total_questions_answered')
    ).join(Response, User.id == Response.user_id)\
     .filter(Response.brier_score.isnot(None))\
     .group_by(User.id, User.nickname)\
     .having(func.count(Response.id) >= min_total_questions_for_ranking)\
     .order_by(asc('average_brier_val'))\
     .limit(top_n).all()

    # --- 4. Overall Top Single Game Scores (from GameSummary table) ---
    top_single_game_scores = db.session.query(
        User.nickname,
        GameSummary.score.label('game_score'),
        GameSummary.game_category,
        GameSummary.completed_at
    ).join(User, User.id == GameSummary.user_id)\
     .order_by(desc('game_score'))\
     .limit(top_n).all()

    # --- 5. Overall Best Single Game Calibration (Avg. Brier from GameSummary table) ---
    top_single_game_briers = db.session.query(
        User.nickname,
        GameSummary.average_brier_score.label('game_brier'),
        GameSummary.game_category,
        GameSummary.completed_at
    ).join(User, User.id == GameSummary.user_id)\
     .filter(GameSummary.average_brier_score.isnot(None))\
     .order_by(asc('game_brier'))\
     .limit(top_n).all()

    # --- 6. Categories eligible for their own leaderboards ---
    #    (Based on total number of games played in that category across all users)
    eligible_categories_query = db.session.query(
        GameSummary.game_category,
        func.count(GameSummary.id).label('total_games_in_category')
    ).filter(GameSummary.game_category.isnot(None))\
     .group_by(GameSummary.game_category)\
     .having(func.count(GameSummary.id) >= min_games_for_cat_lb_display)\
     .order_by(desc('total_games_in_category'), GameSummary.game_category)\
     .all()
    
    eligible_categories = [
        # Use coalesce for display name in case game_category was None (though filtered out above)
        {'name': cat_row.game_category, 'count': cat_row.total_games_in_category}
        for cat_row in eligible_categories_query
    ]
    # Handle if "General Knowledge" was stored as NULL and also as "General Knowledge" string
    # This might require more complex merging if both can exist due to historical data.
    # For now, assuming game_category is consistently stored or coalesced appropriately at game save.
    # If game_category in GameSummary can be NULL for General Knowledge, the query needs coalesce:
    # func.coalesce(GameSummary.game_category, literal_column("'General Knowledge'")).label('display_cat_name')
    # And then group by 'display_cat_name'.

    return render_template('leaderboard.html', title="Leaderboards",
                           top_lifetime_scores=top_lifetime_scores,
                           top_lifetime_accuracy=top_lifetime_accuracy,
                           top_lifetime_brier=top_lifetime_brier,
                           top_single_game_scores=top_single_game_scores,
                           top_single_game_briers=top_single_game_briers,
                           eligible_categories=eligible_categories,
                           get_setting=get_setting # Pass get_setting for use in template if needed for display
                          )

@app.route('/profile')
@login_required # This decorator protects the route
def profile():
    # current_user is automatically available thanks to Flask-Login and user_loader
    # No need to query the user again if they are authenticated.
    return render_template('profile.html', title='My Profile') # current_user is available in the template context

# app.py - /login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: # Use Flask-Login's current_user
        flash('You are already logged in.', 'info')
        return redirect(url_for('index'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user and user.password_hash and check_password_hash(user.password_hash, form.password.data):
            # Use Flask-Login's login_user function
            login_user(user, remember=form.remember.data) # Handles session management

            # Clear old session variables if they exist from pre-Flask-Login era
            session.pop('needs_nickname_setup', None)
            session.pop('suggested_nickname', None)
            # session.pop('user_id', None) # login_user handles this
            # session.pop('nickname', None) # login_user handles this indirectly via current_user

            user.last_login_at = datetime.utcnow()
            db.session.commit()

            flash(f'Welcome back, {user.nickname}!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('index'))
        else:
            flash('Login Unsuccessful. Please check email and password.', 'danger')
    return render_template('login.html', title='Login', form=form)

@app.route('/logout')
def logout():
    user_nickname_before_logout = 'Guest' # Default
    if current_user.is_authenticated:
        user_nickname_before_logout = current_user.nickname
    elif session.get('nickname'): # For nickname-only users
        user_nickname_before_logout = session.get('nickname')
    
    logout_user() # Clears Flask-Login specific session data (_user_id, _remember, etc.)

    # Explicitly clear all custom session keys related to any user identity, setup, or game state
    session.pop('user_id', None)                # From old nickname-only system
    session.pop('nickname', None)               # From old nickname-only system
    session.pop('needs_nickname_setup', None)
    session.pop('suggested_nickname', None)
    session.pop('current_question', None)       # Active game question
    session.pop('last_answer_feedback', None)   # For persistent feedback screen

    # For 'stats', re-initialize to default guest state instead of just popping.
    # This ensures that if they play as a guest immediately after, stats start fresh for that guest session.
    initialize_session_stats(force_reset=True) # Pass a flag to force full reset in initialize_session_stats

    session.modified = True 
    flash(f'You have been logged out, {user_nickname_before_logout}. Play again as a guest or log in!', 'info')
    return redirect(url_for('index'))

@app.route('/clear_last_feedback', methods=['POST'])
def clear_last_feedback():
    if 'last_answer_feedback' in session:
        session.pop('last_answer_feedback', None)
        session.modified = True
        return jsonify({"status": "success", "message": "Feedback cleared."})
    return jsonify({"status": "noop", "message": "No feedback to clear."})

@app.route('/set_nickname', methods=['POST'])
def set_nickname_route():
    if not session.get('needs_nickname_setup'):
        return jsonify({"status": "error", "message": "Nickname setup not pending or already completed."}), 400
    data = request.get_json(); 
    if not data or 'nickname' not in data:
        return jsonify({"status": "error", "message": "Nickname not provided."}), 400
    chosen_nickname = data.get('nickname', '').strip()

    if not (NICKNAME_MIN_LENGTH <= len(chosen_nickname) <= NICKNAME_MAX_LENGTH):
        return jsonify({"status": "error", "message": f"Nickname must be {NICKNAME_MIN_LENGTH}-{NICKNAME_MAX_LENGTH} chars."}), 400
    if not NICKNAME_REGEX.match(chosen_nickname):
        return jsonify({"status": "error", "message": "Nickname: letters, numbers, underscores only."}), 400
    if User.query.filter_by(nickname=chosen_nickname).first():
        return jsonify({"status": "error", "message": "This nickname is already taken. Please choose another."}), 400
    try:
        new_user = User(nickname=chosen_nickname); db.session.add(new_user); db.session.commit()
        session['user_id'] = new_user.id; session['nickname'] = new_user.nickname
        session.pop('needs_nickname_setup', None); session.pop('suggested_nickname', None); session.modified = True
        print(f"User confirmed nickname: {new_user.nickname} (ID: {new_user.id})")
        return jsonify({"status": "success", "nickname": new_user.nickname, "user_id": new_user.id})
    except IntegrityError: db.session.rollback(); return jsonify({"status": "error", "message": "Nickname taken (DB error). Choose another."}), 400
    except Exception as e: db.session.rollback(); print(f"Error creating user {chosen_nickname}: {e}"); return jsonify({"status": "error", "message": "Unexpected error."}), 500

@app.route('/register', methods=['GET', 'POST'])
def register():
    if session.get('user_id'):
        user = User.query.get(session.get('user_id'))
        if user and user.email:
            flash('You are already fully registered and logged in.', 'info')
            return redirect(url_for('index'))
    
    form = RegistrationForm()
    is_claiming_nickname = False # Flag to pass to template

    if request.method == 'GET':
        if session.get('user_id') and session.get('nickname'):
            user_in_db = User.query.get(session.get('user_id'))
            if user_in_db and user_in_db.nickname == session.get('nickname') and not user_in_db.email:
                form.nickname.data = session.get('nickname')
                form.nickname.render_kw = {'readonly': True} # Make the field read-only
                is_claiming_nickname = True 
        elif session.get('needs_nickname_setup') and session.get('suggested_nickname'):
            # This case is for users who might bypass /set_nickname and go directly to /register
            # which is less likely with the current flow but kept for robustness.
            form.nickname.data = session.get('suggested_nickname')

    if form.validate_on_submit():
        hashed_password = generate_password_hash(form.password.data)
        # If nickname field was readonly, form.nickname.data will still give its value.
        nickname_from_form = form.nickname.data
        email_from_form = form.email.data.lower()

        user_to_update = None
        # If user_id is in session, and their DB record has no email, they are claiming.
        # The nickname field would have been pre-filled and made readonly.
        if session.get('user_id'):
            _user = User.query.get(session.get('user_id'))
            # We trust session['nickname'] if user_id is present and matches DB user without email
            if _user and _user.nickname == session.get('nickname') and not _user.email:
                 # Ensure nickname from form (even if readonly) matches session for safety
                if nickname_from_form == _user.nickname:
                    user_to_update = _user
                else:
                    # This should not happen if field is readonly and pre-filled correctly
                    flash("Nickname mismatch during registration. Please try again.", "danger")
                    return render_template('register.html', title='Register', form=form, is_claiming_nickname=is_claiming_nickname)


        if user_to_update: # "Claiming" existing nickname-only account
            # Check if the new email is already taken by ANOTHER user
            existing_email_user = User.query.filter(User.email == email_from_form, User.id != user_to_update.id).first()
            if existing_email_user:
                form.email.errors.append("This email is already registered by another user.")
                return render_template('register.html', title='Register', form=form, is_claiming_nickname=is_claiming_nickname)

            user_to_update.email = email_from_form
            user_to_update.password_hash = hashed_password
            db.session.commit()
            login_user(user_to_update, remember=True)
            flash(f'Account for {user_to_update.nickname} successfully updated with email and password! You are now logged in.', 'success')
            session.pop('needs_nickname_setup', None)
            session.pop('suggested_nickname', None)
            session.modified = True
            return redirect(url_for('index'))
        else: # New registration attempt (e.g., user had no session['user_id'] or something went wrong with claim)
              # This path is now less likely if a user started with nickname selection.
              # It would be for someone hitting /register directly without any prior session.
            
            # Form validators (validate_email, validate_nickname in forms.py)
            # validate_nickname checks if (nickname + email) exists.
            # Here, we need to ensure the nickname isn't taken by ANY registered user if it's a truly new registration.
            existing_registered_user_with_nickname = User.query.filter(User.nickname == nickname_from_form, User.email != None).first()
            if existing_registered_user_with_nickname:
                 form.nickname.errors.append("This nickname is already registered. Please choose another.")
                 return render_template('register.html', title='Register', form=form, is_claiming_nickname=is_claiming_nickname)

            # Check email too (form validator does this, but good for belt-and-suspenders)
            existing_email_user = User.query.filter_by(email=email_from_form).first()
            if existing_email_user:
                form.email.errors.append("This email is already registered. Please use a different one or log in.")
                return render_template('register.html', title='Register', form=form, is_claiming_nickname=is_claiming_nickname)
            
            try: # Create a brand new user
                new_user = User(nickname=nickname_from_form,
                                email=email_from_form,
                                password_hash=hashed_password)
                db.session.add(new_user)
                db.session.commit()
                login_user(new_user, remember=True)
                flash(f'Account created for {new_user.nickname}! You are now logged in.', 'success')
                session['user_id'] = new_user.id
                session['nickname'] = new_user.nickname
                session.pop('needs_nickname_setup', None)
                session.pop('suggested_nickname', None)
                session.modified = True
                return redirect(url_for('index'))
            except IntegrityError as e:
                db.session.rollback()
                if 'users_email_key' in str(e.orig).lower():
                    form.email.errors.append("This email address is already registered.")
                elif 'users_nickname_key' in str(e.orig).lower():
                     form.nickname.errors.append("This nickname is already taken (possibly by a non-registered user, or race condition).")
                else:
                    flash('An unexpected error occurred (DB constraint). Please try again.', 'danger')
                return render_template('register.html', title='Register', form=form, is_claiming_nickname=is_claiming_nickname)
            except Exception as e:
                db.session.rollback()
                print(f"Error creating new user: {e}")
                flash('An error occurred while creating your account. Please try again.', 'danger')
                return render_template('register.html', title='Register', form=form)
    
    return render_template('register.html', title='Register', form=form, is_claiming_nickname=is_claiming_nickname)

@app.route('/get_user_selectable_categories', methods=['GET'])
def get_user_selectable_categories():
    categories_str = get_setting('user_selectable_categories', ''); categories_list = [cat.strip() for cat in categories_str.split(',') if cat.strip()]; return jsonify({'categories': categories_list})

@app.route('/get_trivia_question', methods=['GET'])
@nickname_setup_required
def get_trivia_question(user): 
    initialize_session_stats(); user_category_custom_raw = request.args.get('user_category_custom'); user_category_prefab = request.args.get('user_category_prefab'); processed_user_theme = None; game_category_for_session_stats = None
    if user_category_custom_raw: processed_user_theme = get_standardized_category_via_gemini(user_category_custom_raw); game_category_for_session_stats = f"Custom: {processed_user_theme}"
    elif user_category_prefab and user_category_prefab != 'random': processed_user_theme = user_category_prefab; game_category_for_session_stats = processed_user_theme
    if game_category_for_session_stats is None:
        game_category_for_session_stats = "General Knowledge"
    session['stats']['current_game_category'] = game_category_for_session_stats; session.modified = True
    min_summary_words = get_setting('min_summary_words', 50); gemini_context_length = get_setting('gemini_context_length', 3000); admin_strategy = get_setting('page_selection_strategy', 'random').lower(); admin_keywords = get_setting('search_keywords', 'History,Science'); admin_categories = get_setting('target_categories', 'Physics,WWII'); admin_limit = get_setting('api_result_limit', 20)
    print(f"\n--- Requesting new Q for user: {user.nickname} ---"); print(f"Game theme: '{processed_user_theme}'" if processed_user_theme else f"Admin settings: Strategy='{admin_strategy}'")
    page = None; question = None; options = None; correct_answer = None; generation_attempt = 0
    while generation_attempt < MAX_GENERATION_ATTEMPTS:
        generation_attempt += 1; print(f"\nOverall Q&A Gen Attempt {generation_attempt}/{MAX_GENERATION_ATTEMPTS}")
        page = get_wikipedia_page(admin_strategy, admin_keywords, admin_categories, admin_limit, user_category_theme=processed_user_theme)
        if not page: 
            if generation_attempt >= MAX_GENERATION_ATTEMPTS: error_message = f"Failed to find article after {MAX_GENERATION_ATTEMPTS} attempts." + (f" Try different category: '{processed_user_theme[:50]}...'." if processed_user_theme else " Try again."); session['stats']['current_game_category'] = None; session.modified = True; return jsonify({"error": error_message}), 503
            continue
        wiki_page_title = page.title; wiki_page_url = page.fullurl; summary = page.summary; print(f"Page: '{wiki_page_title}'. Summary words: {len(summary.split())}.")
        if len(summary.split()) < min_summary_words: 
            if generation_attempt >= MAX_GENERATION_ATTEMPTS: session['stats']['current_game_category'] = None; session.modified = True; return jsonify({"error": f"Failed to find articles with long summaries. Try broader category."}), 503
            page = None; continue
        question, options, correct_answer = generate_question_from_text(summary, gemini_context_length, game_theme=processed_user_theme)
        if question and options and correct_answer: print(f"Generated Q&A for '{wiki_page_title}'."); break
        else: page = None;
    if not (page and question and options and correct_answer): 
        final_error_message = "Failed to generate Q. " + (f"Topic '{processed_user_theme[:50]}...' too niche? Try different." if processed_user_theme else "Try again."); session['stats']['current_game_category'] = None; session.modified = True; return jsonify({"error": final_error_message}), 503
    display_category_name_for_session_and_render = game_category_for_session_stats if game_category_for_session_stats else "General Knowledge"
    session['current_question'] = {'title': wiki_page_title, 'url': wiki_page_url, 'question': question, 'options': options, 'correct_answer_letter': correct_answer, 'category_for_game': game_category_for_session_stats, 'display_category_name': display_category_name_for_session_and_render}; session.modified = True
    return jsonify({'question': question, 'options': options, 'wiki_page_title': wiki_page_title, 'wiki_page_url': wiki_page_url, 'display_category_name': display_category_name_for_session_and_render})

@app.route('/submit_answer', methods=['POST'])
@nickname_setup_required # Or @login_required if you shift to that for game actions
def submit_answer(user): 
    initialize_session_stats()
    data = request.get_json()
    user_answer_letter = data.get('answer')
    user_confidence = data.get('confidence')

    if 'current_question' not in session: # If no active question (e.g., due to refresh after feedback was already shown)
        # Check if there's feedback to re-display from a previous submission on this "game turn"
        if session.get('last_answer_feedback'):
            # This implies they refreshed on the feedback screen.
            # The index route will handle re-rendering this feedback.
            # We don't need to do anything here other than acknowledge this state.
            # Or, we could return the feedback directly, but letting index handle it is cleaner.
            return jsonify(session['last_answer_feedback']) # Return the stored feedback
        return jsonify({"error": "No active question. Please start a new one.", "action_needed": "get_new_question"}), 400

    if user_answer_letter is None or user_confidence is None:
        return jsonify({"error": "Missing answer or confidence."}), 400
    
    try:
        user_confidence = int(user_confidence)
        assert 0 <= user_confidence <= 100
    except (ValueError, AssertionError): # Catch both potential errors
        return jsonify({"error": "Invalid confidence value."}), 400

    current_q = session['current_question']
    game_category_for_db = session['stats'].get('current_game_category')
    correct_answer_letter = current_q['correct_answer_letter']
    correct_answer_text = current_q['options'].get(correct_answer_letter)
    is_correct = (user_answer_letter == correct_answer_letter)
    brier_score = calculate_brier_score(user_confidence, is_correct)
    points = 0.0

    try:
        base_correct = float(get_setting('score_base_correct', 10.0))
        mult_correct = float(get_setting('score_mult_correct', 0.9))
        base_incorrect = float(get_setting('score_base_incorrect', -100.0))
        mult_incorrect = float(get_setting('score_mult_incorrect', 0.9))
        if is_correct:
            points = base_correct + (mult_correct * user_confidence)
        else:
            points = base_incorrect + (mult_incorrect * (100 - user_confidence))
        points = round(points, 2)
    except Exception as e:
        print(f"Error calculating score: {e}")
        points = 0.0 # Default to 0 if error in calculation

    stats = session['stats']
    stats['total_answered'] += 1
    if is_correct:
        stats['total_correct'] += 1
    
    stats['brier_scores'].append(brier_score)
    stats['game_brier_scores'].append(brier_score)
    stats['confidence_levels'].append(user_confidence)
    stats['correctness'].append(is_correct)
    stats['cumulative_score'] += points
    stats['cumulative_score'] = round(stats['cumulative_score'], 2)
    stats['questions_this_game'] += 1

    game_length = int(get_setting('game_length', 20))
    end_of_game = (stats['questions_this_game'] >= game_length)

    stats_snapshot_for_client = stats.copy()
    stats_snapshot_for_client['game_length_setting'] = game_length

    if end_of_game:
       stats['completed_game_scores_session'].append(stats['cumulative_score'])
       print(f"Game ended for {user.nickname if user else 'guest'}. Qs: {stats['questions_this_game']}, Score: {stats['cumulative_score']}, Cat: {game_category_for_db}")

       if user: # Only save game summaries for registered/identified users
           try:
               game_avg_brier = None
               if stats['game_brier_scores']: # Calculate average Brier for this game
                   game_avg_brier = sum(stats['game_brier_scores']) / len(stats['game_brier_scores'])
               
               summary = GameSummary(
                   user_id=user.id,
                   game_category=game_category_for_db, # This comes from session['stats']['current_game_category']
                   score=stats['cumulative_score'],
                   average_brier_score=game_avg_brier,
                   questions_answered=stats['questions_this_game'] # Should be game_length
                   # game_length_setting=game_length # Optional: if you want to store it
               )
               db.session.add(summary)
               db.session.commit()
               print(f"GameSummary saved for user {user.id}, category {game_category_for_db}, score {summary.score}")
           except Exception as e:
               db.session.rollback()
               print(f"Error saving GameSummary: {e}")

    feedback_data = {
        "result": "correct" if is_correct else "incorrect",
        "correct_answer_letter": correct_answer_letter,
        "correct_answer_text": correct_answer_text,
        "options": current_q['options'],
        "user_answer_letter": user_answer_letter,
        "brier_score": round(brier_score, 3),
        "points_awarded": points,
        "new_stats": stats_snapshot_for_client, # Send a copy of the updated stats
        "end_of_game": end_of_game,
        "wiki_page_title": current_q['title'], # For context if needed
        "question_text": current_q['question'],
        "display_category_name": current_q.get('display_category_name', "General")
    }
    session['last_answer_feedback'] = feedback_data

    current_session_stats_for_response = stats.copy() # Use the updated stats for the immediate JSON response
    current_session_stats_for_response['game_length_setting'] = game_length
    
    session.pop('current_question', None) # Clear current_question AFTER preparing feedback
    session.modified = True

    try:
        response_entry = Response(
            user_id=user.id, 
            wiki_page_title=current_q['title'], 
            question_text=current_q['question'], 
            answer_options=str(current_q['options']), 
            correct_answer=correct_answer_letter, 
            user_answer=user_answer_letter, 
            user_confidence=user_confidence, 
            is_correct=is_correct, 
            brier_score=brier_score, 
            points_awarded=points, 
            game_category=game_category_for_db
        )
        db.session.add(response_entry)
        db.session.commit()
        print(f"Response saved. User: {user.nickname if user else 'guest'}, Points: {points}, Cat: '{game_category_for_db}'")
    except Exception as e:
        db.session.rollback()
        print(f"Error saving response for user {user.id if user else 'unknown'}: {e}")
    
    # Return the feedback_data directly, JS will use this or the session stored one on refresh
    return jsonify(feedback_data)

@app.route('/submit_feedback', methods=['GET', 'POST'])
def submit_feedback():
    form = FeedbackForm()

    if form.validate_on_submit():
        # Form submitted and validated
        feedback_message = form.message.data
        feedback_type = form.feedback_type.data
        email_at_submission = form.email.data if form.email.data else None # Use None if empty

        user_id_for_feedback = None
        nickname_for_feedback = "Guest" # Default for display
        
        if current_user.is_authenticated:
            user_id_for_feedback = current_user.id
            nickname_for_feedback = current_user.nickname
            # If logged-in user didn't provide an email in the form, use their registered one
            if not email_at_submission and current_user.email:
                email_at_submission = current_user.email
        
        user_agent = request.user_agent.string
        # Try to get referring page as context, fallback if not available
        page_ctx = request.referrer or request.path 

        try:
            new_feedback = UserFeedback(
                user_id=user_id_for_feedback,
                email_address_at_submission=email_at_submission,
                nickname_at_submission=nickname_for_feedback if user_id_for_feedback else (form.email.data or "Anonymous Guest"), # More specific guest nickname
                feedback_type=feedback_type,
                message=feedback_message,
                user_agent_string=user_agent[:255], # Truncate if too long
                page_context=page_ctx[:255] # Truncate if too long
            )
            db.session.add(new_feedback)
            db.session.commit()
            flash('Thank you for your feedback! We appreciate you helping us improve.', 'success')
            return redirect(url_for('index')) # Or redirect to a dedicated "thank you" page or back
        except Exception as e:
            db.session.rollback()
            print(f"Error saving feedback: {e}")
            flash('Sorry, there was an error submitting your feedback. Please try again.', 'danger')

    # For GET request, or if form validation fails on POST:
    # Pre-fill email if user is logged in and didn't provide one in a previous attempt (if form re-renders on error)
    elif request.method == 'GET' and current_user.is_authenticated and current_user.email:
        if not form.email.data: # Only if form email is currently empty
             form.email.data = current_user.email
             
    return render_template('submit_feedback.html', title='Submit Feedback', form=form)

@app.route('/get_stats')
def get_stats():
    # initialize_session_stats() ensures session['stats'] exists and is up-to-date
    # with all keys, including any defaults if some were missing.
    current_stats = initialize_session_stats() # Get the current session's stats
    current_stats['game_length_setting'] = int(get_setting('game_length', 20)) # Ensure it's here
    return jsonify(current_stats)

@app.route('/get_calibration_data')
def get_calibration_data():
    confidence_levels = []
    correctness = []

    # --- STAGE 2: User Control for Number of Bins ---
    # Try to get 'bins' from query parameter first
    num_bins_from_query = request.args.get('bins', type=int)
    
    num_bins = 10 # Overall default

    if num_bins_from_query is not None:
        if 2 <= num_bins_from_query <= 50: # Sanity check for user-provided value
            num_bins = num_bins_from_query
            print(f"DEBUG: Using num_bins from query parameter: {num_bins}")
        else:
            print(f"Warning: User-provided 'bins' value {num_bins_from_query} out of range (2-50). Using AppSetting or default.")
            # Fall through to AppSetting if user value is bad
            num_bins_from_query = None # Mark as invalid so AppSetting is checked

    if num_bins_from_query is None: # If not provided by user or user value was bad
        try:
            num_bins_str = get_setting('calibration_chart_bins', '10')
            num_bins_setting = int(num_bins_str)
            if not (2 <= num_bins_setting <= 50):
                print(f"Warning: AppSetting 'calibration_chart_bins' value {num_bins_setting} out of range (2-50). Defaulting to 10.")
                num_bins = 10
            else:
                num_bins = num_bins_setting
                print(f"DEBUG: Using num_bins from AppSetting: {num_bins}")
        except ValueError:
            print("Warning: Could not parse 'calibration_chart_bins' from AppSetting. Defaulting to 10.")
            num_bins = 10
    # --- End get number of bins ---


    # --- Fetch Data: Lifetime for logged-in, Session for guests ---
    if current_user.is_authenticated:
        responses = Response.query.filter_by(user_id=current_user.id)\
                            .with_entities(Response.user_confidence, Response.is_correct)\
                            .filter(Response.user_confidence.isnot(None))\
                            .all()
        if responses:
            confidence_levels = [r.user_confidence for r in responses]
            correctness = [r.is_correct for r in responses]
        print(f"DEBUG: Fetched {len(confidence_levels)} lifetime responses for calibration chart for user {current_user.id}")
    else: # Guest user
        stats = initialize_session_stats()
        cl = stats.get('confidence_levels')
        cr = stats.get('correctness')
        confidence_levels = cl if isinstance(cl, list) else []
        correctness = cr if isinstance(cr, list) else []
        print(f"DEBUG: Using {len(confidence_levels)} session responses for calibration chart for guest.")
    # --- End Fetch Data ---

    if not confidence_levels or num_bins < 1 :
        print("DEBUG: No confidence levels or invalid num_bins, returning empty points for chart.")
        return jsonify({"points": []})

    # --- Binning Logic (as before, now using the determined num_bins) ---
    counts = [0] * num_bins
    correct_counts = [0] * num_bins
    sum_confidence_per_bin = [0.0] * num_bins

    for conf, correct_flag in zip(confidence_levels, correctness):
        try:
            conf_int = int(conf)
            if not (0 <= conf_int <= 100):
                continue
            
            if conf_int == 100:
                bin_index = num_bins - 1
            elif conf_int == 0: # Ensures 0 goes into bin 0
                bin_index = 0
            else: # For confidence > 0 and < 100
                bin_width = 100.0 / num_bins 
                bin_index = math.floor((conf_int - 1) / bin_width)
            
            bin_index = max(0, min(bin_index, num_bins - 1)) # Clamp to 0 to num_bins-1

            counts[bin_index] += 1
            sum_confidence_per_bin[bin_index] += conf_int
            if correct_flag:
                correct_counts[bin_index] += 1
        except ValueError:
            continue
            
    chart_points = []
    for i in range(num_bins):
        if counts[i] > 0:
            avg_conf_in_bin = sum_confidence_per_bin[i] / counts[i]
            accuracy_in_bin = correct_counts[i] / counts[i]
            chart_points.append({
                'x': avg_conf_in_bin,
                'y': accuracy_in_bin,
                'count': counts[i]
            })
    
    print(f"DEBUG: Returning {len(chart_points)} points for calibration chart with {num_bins} bins.")
    return jsonify({'points': chart_points})

@app.route('/start_new_game', methods=['POST'])
@nickname_setup_required 
def start_new_game_route(user): # 'user' object is passed by the decorator
    # Clear previous game/feedback state from session
    session.pop('current_question', None)
    session.pop('last_answer_feedback', None)

    # Get existing session stats or initialize if somehow missing
    # initialize_session_stats() ensures session['stats'] exists
    current_stats = initialize_session_stats() 

    # Reset game-specific stats, increment games_played_session
    current_stats['games_played_session'] += 1
    current_stats['cumulative_score'] = 0.0
    current_stats['questions_this_game'] = 0
    current_stats['game_brier_scores'] = []
    current_stats['current_game_category'] = None 
    
    # For the calibration chart: decide if you want to clear these session-wide accumulators
    # or let them accumulate for the entire browser session for guests/logged-in users.
    # If clearing per game:
    # current_stats['confidence_levels'] = []
    # current_stats['correctness'] = []
    # current_stats['brier_scores'] = [] # This would clear the overall session brier too

    session['stats'] = current_stats # Put the modified stats back into the session
    session.modified = True

    print(f"New game started for user: {user.nickname if user else 'guest'}. Game-specific stats reset.")
    
    # Prepare payload for JS
    stats_payload = current_stats.copy()
    stats_payload['game_length_setting'] = int(get_setting('game_length', 20))
    
    return jsonify({"status": "success", "new_stats": stats_payload})

# --- Main Execution & DB Initialization ---
if __name__ == '__main__':
    with app.app_context():
        print("Ensuring database tables exist..."); db.create_all(); print("Tables checked/created.")
        print("Checking for default AppSettings...")
        defaults = {
            'min_summary_words': ('50', 'Minimum words in Wikipedia summary to attempt question generation'),
            'gemini_context_length': ('3000', 'Max characters of summary sent to Gemini API'),
            'page_selection_strategy': ('random', 'Method to select Wikipedia pages (random, search, category) - Admin default'),
            'search_keywords': ('History, Science, Technology, Art, Geography, Culture, Philosophy, Sports', 'Comma-separated keywords for admin search strategy'),
            'target_categories': ('Physics, World_War_II, Cities_in_France, Mammals, Programming_languages', 'Comma-separated categories for admin category strategy (no "Category:" prefix)'),
            'user_selectable_categories': ('World History, Space Exploration, Ancient Civilizations, Modern Art, Programming Languages, Mythology, Film Directors, Famous Battles', 'Comma-separated list of predefined categories for users to select for their game.'),
            'api_result_limit': ('20', 'Max results to fetch/consider from admin search/category API calls'),
            'score_base_correct': ('10', 'Base points for correct answer at 0% confidence'),
            'score_mult_correct': ('0.9', 'Additional points per confidence % for correct answer (e.g., 0.9*conf)'),
            'score_base_incorrect': ('-100', 'Base points (penalty) for incorrect answer at 100% confidence'),
            'score_mult_incorrect': ('0.9', 'Reduction in penalty per confidence % *below* 100 for incorrect answer (e.g., base + 0.9*(100-conf))'),
            'game_length': ('20', 'Number of questions per game session'),
            'calibration_chart_bins': ('10', 'Number of bins for the calibration chart (e.g., 5, 10, 20)'),
            'min_questions_for_cat_rank': ('5', 'Min questions answered in a category to be considered for best/worst category ranking'),
            'leaderboard_top_n_users': ('25', 'Number of users to display on leaderboards'),
            'leaderboard_min_games_for_lifetime_ranking': ('3', 'Minimum number of COMPLETED GAMES for user to appear on lifetime Brier/Accuracy leaderboards'),
            'leaderboard_min_games_for_category_leaderboard': ('1', 'Minimum number of COMPLETED GAMES in a category for that category to have its own leaderboard section/link'),
            'leaderboard_min_games_for_category_ranking': ('3', 'Minimum number of COMPLETED GAMES a user must have in a specific category to appear on that category\'s Brier/Accuracy leaderboard')
        }
        added_defaults = False
        for key, (value, setting_description) in defaults.items():
            if not AppSetting.query.filter_by(setting_key=key).first():
                print(f"Adding default setting: {key} = {value}"); db.session.add(AppSetting(setting_key=key, setting_value=value, description=setting_description)); added_defaults = True
        if added_defaults: db.session.commit(); print("Default settings committed.")
        else: print("All default settings already exist.")
    print("Starting Flask application..."); app.run(debug=True, host='0.0.0.0', port=5000)