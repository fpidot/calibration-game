# app.py (Corrected for User Nickname Choice Feature)

import os
import random
import re 
import requests
import math
from flask import Flask, render_template, request, jsonify, session, flash
from flask_migrate import Migrate
from flask_admin import Admin
from dotenv import load_dotenv
import google.generativeai as genai
import wikipediaapi
from sqlalchemy.exc import IntegrityError
from functools import wraps

# --- App Configuration ---
load_dotenv()
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')

# --- Database Setup ---
from models import db 
db.init_app(app) 
migrate = Migrate(app, db)

# --- Database Models ---
from models import User, Response, AppSetting # Corrected: db is already imported

# --- Admin Setup ---
from admin_views import AppSettingAdminView, ResponseAdminView, UserAdminView 
admin = Admin(app, name='Trivia Admin', template_mode='bootstrap3')
admin.add_view(AppSettingAdminView(AppSetting, db.session))
admin.add_view(ResponseAdminView(Response, db.session))
admin.add_view(UserAdminView(User, db.session)) 

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
    if session.get('user_id') and session.get('nickname') and not session.get('needs_nickname_setup'):
        user = User.query.get(session['user_id'])
        if user and user.nickname == session['nickname']:
            return user 
        else: 
            print(f"User ID {session.get('user_id')} or nickname mismatch with DB. Resetting session for new user setup.")
            session.clear() # Clear entire session on mismatch for fresh start

    if 'needs_nickname_setup' not in session or not session.get('needs_nickname_setup'): # Check flag explicitly
        print("User not fully set up or new session. Initiating nickname setup phase.")
        suggested_nick = generate_suggested_nickname()
        session['needs_nickname_setup'] = True
        session['suggested_nickname'] = suggested_nick
    
    session.modified = True
    return None 

def nickname_setup_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('needs_nickname_setup'):
            return jsonify({"error": "Nickname setup required.", "action_needed": "complete_nickname_setup"}), 403
        user_id_in_session = session.get('user_id'); nickname_in_session = session.get('nickname')
        if not user_id_in_session or not nickname_in_session:
            print("Decorator: User ID or Nickname missing from session, forcing setup.")
            session['needs_nickname_setup'] = True ; session['suggested_nickname'] = generate_suggested_nickname(); session.modified = True
            return jsonify({"error": "User session incomplete. Please set nickname.", "action_needed": "complete_nickname_setup"}), 403
        user = User.query.get(user_id_in_session)
        if not user or user.nickname != nickname_in_session: 
            print(f"Decorator: User session invalid (ID: {user_id_in_session}, Nick: {nickname_in_session}, DB User: {user}). Forcing re-setup.")
            session.clear(); session['needs_nickname_setup'] = True; session['suggested_nickname'] = generate_suggested_nickname(); session.modified = True
            return jsonify({"error": "User session invalid. Please complete nickname setup again.", "action_needed": "complete_nickname_setup"}), 403
        return f(user, *args, **kwargs) 
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

def initialize_session_stats():
    default_stats = {'total_answered': 0, 'total_correct': 0, 'brier_scores': [], 'game_brier_scores': [], 'confidence_levels': [], 'correctness': [], 'cumulative_score': 0.0, 'questions_this_game': 0, 'games_played_session': 0, 'completed_game_scores_session': [], 'current_game_category': None }
    if 'stats' not in session: session['stats'] = default_stats.copy(); print("New session: Initialized all stats.")
    else:
        updated = False;
        for key, default_val in default_stats.items():
            if key not in session['stats']: session['stats'][key] = default_val; updated = True
        if updated: print("Existing session: Ensured all stat keys are present.")
    session.modified = True

# --- Routes ---
@app.route('/')
def index():
    user = ensure_user_session_initialized() 
    initialize_session_stats() 
    active_question_data = session.get('current_question') 
    
    template_vars = {
        'active_question_data': active_question_data,
        'user_info': None,
        'needs_nickname_setup': session.get('needs_nickname_setup', False),
        'suggested_nickname': session.get('suggested_nickname')
    }
    if user: 
        template_vars['user_info'] = {'nickname': user.nickname, 'user_id': user.id }
    # If user is None but nickname setup is NOT pending (e.g. error in ensure_user_session_initialized)
    # and there's a nickname in session, pass that for display continuity.
    elif session.get('nickname') and not session.get('needs_nickname_setup'):
        template_vars['user_info'] = {'nickname': session.get('nickname'), 'user_id': session.get('user_id')}

    return render_template('index.html', **template_vars)

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

@app.route('/get_user_selectable_categories', methods=['GET'])
def get_user_selectable_categories():
    categories_str = get_setting('user_selectable_categories', ''); categories_list = [cat.strip() for cat in categories_str.split(',') if cat.strip()]; return jsonify({'categories': categories_list})

@app.route('/get_trivia_question', methods=['GET'])
@nickname_setup_required
def get_trivia_question(user): 
    initialize_session_stats(); user_category_custom_raw = request.args.get('user_category_custom'); user_category_prefab = request.args.get('user_category_prefab'); processed_user_theme = None; game_category_for_session_stats = None
    if user_category_custom_raw: processed_user_theme = get_standardized_category_via_gemini(user_category_custom_raw); game_category_for_session_stats = f"Custom: {processed_user_theme}"
    elif user_category_prefab and user_category_prefab != 'random': processed_user_theme = user_category_prefab; game_category_for_session_stats = processed_user_theme
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
@nickname_setup_required
def submit_answer(user): 
    initialize_session_stats(); data = request.get_json(); user_answer_letter = data.get('answer'); user_confidence = data.get('confidence')
    if 'current_question' not in session: return jsonify({"error": "No active question."}), 400
    if user_answer_letter is None or user_confidence is None: return jsonify({"error": "Missing answer/confidence."}), 400
    try: user_confidence = int(user_confidence); assert 0 <= user_confidence <= 100
    except: return jsonify({"error": "Invalid confidence."}), 400
    current_q = session['current_question']; game_category_for_db = session['stats'].get('current_game_category'); correct_answer_letter = current_q['correct_answer_letter']; correct_answer_text = current_q['options'].get(correct_answer_letter); is_correct = (user_answer_letter == correct_answer_letter); brier_score = calculate_brier_score(user_confidence, is_correct); points = 0.0
    try:
        base_correct = float(get_setting('score_base_correct', 10.0)); mult_correct = float(get_setting('score_mult_correct', 0.9)); base_incorrect = float(get_setting('score_base_incorrect', -100.0)); mult_incorrect = float(get_setting('score_mult_incorrect', 0.9))
        if is_correct: points = base_correct + (mult_correct * user_confidence)
        else: points = base_incorrect + (mult_incorrect * (100 - user_confidence))
        points = round(points, 2)
    except Exception as e: print(f"Error calculating score: {e}");
    stats = session['stats']; stats['total_answered'] += 1;
    if is_correct: stats['total_correct'] += 1
    stats['brier_scores'].append(brier_score); stats['game_brier_scores'].append(brier_score); stats['confidence_levels'].append(user_confidence); stats['correctness'].append(is_correct); stats['cumulative_score'] += points; stats['cumulative_score'] = round(stats['cumulative_score'], 2); stats['questions_this_game'] += 1
    game_length = int(get_setting('game_length', 20)); end_of_game = (stats['questions_this_game'] >= game_length)
    if end_of_game: stats['completed_game_scores_session'].append(stats['cumulative_score']); print(f"Game ended for {user.nickname}. Qs: {stats['questions_this_game']}, Score: {stats['cumulative_score']}, Cat: {game_category_for_db}")
    current_session_stats = session['stats'].copy(); current_session_stats['game_length_setting'] = game_length; session.pop('current_question', None); session.modified = True
    try:
        response_entry = Response(user_id=user.id, wiki_page_title=current_q['title'], question_text=current_q['question'], answer_options=str(current_q['options']), correct_answer=correct_answer_letter, user_answer=user_answer_letter, user_confidence=user_confidence, is_correct=is_correct, brier_score=brier_score, points_awarded=points, game_category=game_category_for_db)
        db.session.add(response_entry); db.session.commit(); print(f"Response saved. User: {user.nickname}, Points: {points}, Cat: '{game_category_for_db}'")
    except Exception as e: db.session.rollback(); print(f"Error saving response for user {user.id}: {e}")
    return jsonify({"result": "correct" if is_correct else "incorrect", "correct_answer": correct_answer_letter, "correct_answer_text": correct_answer_text, "brier_score": round(brier_score, 3), "points_awarded": points, "new_stats": current_session_stats, "end_of_game": end_of_game })

@app.route('/get_stats')
def get_stats():
    initialize_session_stats(); current_stats = session['stats'].copy(); current_stats['game_length_setting'] = int(get_setting('game_length', 20)); return jsonify(current_stats)

@app.route('/get_calibration_data')
def get_calibration_data():
    initialize_session_stats(); stats = session['stats']
    if not stats.get('confidence_levels'): return jsonify({"points": []})
    confidence_levels = stats.get('confidence_levels', []); correctness = stats.get('correctness', [])
    if not isinstance(confidence_levels, list): confidence_levels = []
    if not isinstance(correctness, list): correctness = []
    num_bins = 10; counts = [0] * num_bins; correct_counts = [0] * num_bins; sum_confidence_per_bin = [0.0] * num_bins
    if not confidence_levels: return jsonify({"points": []})
    for conf, correct in zip(confidence_levels, correctness):
        try:
            conf_int = int(conf);
            if not (0 <= conf_int <= 100): continue
            bin_index = num_bins - 1 if conf_int == 100 else conf_int // (100 // num_bins); bin_index = max(0, min(bin_index, num_bins - 1))
            counts[bin_index] += 1; sum_confidence_per_bin[bin_index] += conf_int
            if correct: correct_counts[bin_index] += 1
        except ValueError: print(f"Warning: Could not convert confidence '{conf}' to int for calibration chart."); continue
    chart_points = [];
    for i in range(num_bins):
        if counts[i] > 0: chart_points.append({'x': sum_confidence_per_bin[i] / counts[i], 'y': correct_counts[i] / counts[i], 'count': counts[i]})
    return jsonify({'points': chart_points})

@app.route('/start_new_game', methods=['POST'])
@nickname_setup_required
def start_new_game(user): 
    initialize_session_stats(); stats = session['stats']
    stats['games_played_session'] += 1; stats['cumulative_score'] = 0.0; stats['questions_this_game'] = 0; stats['game_brier_scores'] = []; stats['confidence_levels'] = []; stats['correctness'] = []; stats['current_game_category'] = None 
    session['stats'] = stats; session.modified = True
    print(f"New game started for user: {user.nickname}. Session stats reset for game-specific items.")
    current_stats_payload = session['stats'].copy(); current_stats_payload['game_length_setting'] = int(get_setting('game_length', 20))
    return jsonify({"status": "success", "new_stats": current_stats_payload})

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
            'game_length': ('20', 'Number of questions per game session') 
        }
        added_defaults = False
        for key, (value, desc) in defaults.items():
            if not AppSetting.query.filter_by(setting_key=key).first():
                print(f"Adding default setting: {key} = {value}"); db.session.add(AppSetting(setting_key=key, setting_value=value, description=desc)); added_defaults = True
        if added_defaults: db.session.commit(); print("Default settings committed.")
        else: print("All default settings already exist.")
    print("Starting Flask application..."); app.run(debug=True, host='0.0.0.0', port=5000)