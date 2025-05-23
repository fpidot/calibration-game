# app.py

import os
import random
import requests
import math
from flask import Flask, render_template, request, jsonify, session, flash
from flask_migrate import Migrate
from flask_admin import Admin
from dotenv import load_dotenv
import google.generativeai as genai
import wikipediaapi

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
from models import Response, AppSetting

# --- Admin Setup ---
from admin_views import AppSettingAdminView, ResponseAdminView
admin = Admin(app, name='Trivia Admin', template_mode='bootstrap3')
admin.add_view(AppSettingAdminView(AppSetting, db.session))
admin.add_view(ResponseAdminView(Response, db.session))

# --- API Setups ---
wiki_user_agent_contact = os.getenv('WIKI_USER_AGENT_CONTACT', 'your_email@example.com')
WIKI_USER_AGENT = f'WikipediaTriviaGame/1.0 (https://github.com/fpidot/calibration-game; {wiki_user_agent_contact})'
wiki_wiki = wikipediaapi.Wikipedia(user_agent=WIKI_USER_AGENT, language='en')

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
model = None
if not GEMINI_API_KEY: print("Warning: GEMINI_API_KEY not set. Question generation disabled.")
else:
    try: genai.configure(api_key=GEMINI_API_KEY); model = genai.GenerativeModel('gemini-1.5-flash'); print("Gemini API configured.")
    except Exception as e: print(f"Error configuring Gemini API: {e}.")

# --- Constants ---
PAGE_FETCH_ATTEMPTS = 5
MAX_GENERATION_ATTEMPTS = 3

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
            return value_type(setting.setting_value)
        except (ValueError, TypeError): return default_value
    return default_value

def get_wikipedia_page(strategy, keywords_str, categories_str, limit):
    selected_title = None; attempts = 0
    while attempts < PAGE_FETCH_ATTEMPTS:
        attempts += 1; print(f"Page Fetch Attempt {attempts}/{PAGE_FETCH_ATTEMPTS} using strategy: {strategy}")
        current_strategy = strategy; headers = {'User-Agent': WIKI_USER_AGENT}
        try:
            if current_strategy == 'search':
                keywords = [k.strip() for k in keywords_str.split(',') if k.strip()]
                if not keywords: print("Warning: No search keywords. Falling back to random."); current_strategy = 'random'
                else:
                    keyword = random.choice(keywords); print(f"Searching: {keyword}")
                    S = requests.Session(); URL = "https://en.wikipedia.org/w/api.php"; PARAMS = {"action": "query","format": "json","list": "search","srsearch": keyword,"srnamespace": "0","srlimit": limit,"srwhat": "text"}
                    R = S.get(url=URL, params=PARAMS, headers=headers); R.raise_for_status(); data = R.json()
                    search_results = data.get("query", {}).get("search", [])
                    if search_results: selected_title = random.choice(search_results)['title']; print(f"Selected '{selected_title}' from search.")
                    else: print(f"No results for '{keyword}'. Retrying."); continue
            elif current_strategy == 'category':
                categories = [c.strip() for c in categories_str.split(',') if c.strip()]
                if not categories: print("Warning: No categories. Falling back to random."); current_strategy = 'random'
                else:
                    category_name_base = random.choice(categories)
                    category_name = category_name_base if category_name_base.lower().startswith("category:") else f"Category:{category_name_base}"
                    print(f"Fetching for category: {category_name}")
                    S = requests.Session(); URL = "https://en.wikipedia.org/w/api.php"; PARAMS = {"action": "query","format": "json","list": "categorymembers","cmtitle": category_name,"cmlimit": limit,"cmtype": "page","cmprop": "title"}
                    R = S.get(url=URL, params=PARAMS, headers=headers); R.raise_for_status(); data = R.json()
                    members = data.get("query", {}).get("categorymembers", [])
                    if members: selected_title = random.choice(members)['title']; print(f"Selected '{selected_title}' from category.")
                    else: print(f"No members in '{category_name}'. Retrying."); continue
            if current_strategy == 'random' or (selected_title is None and current_strategy != 'random'):
                print("Using random strategy or fallback."); S = requests.Session(); URL = "https://en.wikipedia.org/w/api.php"; PARAMS = {"action": "query","format": "json","list": "random","rnnamespace": "0","rnlimit": "1"}
                R = S.get(url=URL, params=PARAMS, headers=headers); R.raise_for_status(); data = R.json()
                random_pages = data.get("query", {}).get("random", [])
                if random_pages: selected_title = random_pages[0]["title"]; print(f"Selected random: {selected_title}")
                else: print("Random API failed. Retrying."); continue
            if selected_title:
                print(f"Fetching content for: {selected_title}"); page = wiki_wiki.page(selected_title)
                if page and page.exists():
                    summary_lower = page.summary.lower(); min_summary_words_check = get_setting('min_summary_words', 50)
                    is_disambiguation = "may refer to:" in summary_lower or page.title.lower().endswith("(disambiguation)")
                    is_stub = len(page.sections) <= 1 and len(summary_lower.split()) < max(10, min_summary_words_check // 2)
                    if is_disambiguation: print(f"'{selected_title}' is disambiguation. Retrying."); selected_title = None; continue
                    if is_stub: print(f"'{selected_title}' is stub. Retrying."); selected_title = None; continue
                    print(f"Validated: {page.title}"); return page
                else: print(f"'{selected_title}' not found/exists. Retrying."); selected_title = None
        except requests.exceptions.RequestException as e: print(f"Network error: {e}. Retrying."); selected_title = None
        except Exception as e: print(f"Unexpected error: {e}. Retrying."); selected_title = None
    print(f"Failed page fetch after {PAGE_FETCH_ATTEMPTS} attempts."); return None

def generate_question_from_text(text, context_length):
    if not text: print("Error: Empty text for Q gen."); return None,None,None
    if model is None: print("Error: Gemini model unavailable."); return None,None,None
    text_to_send = text[:context_length]; prompt = f"""Create a multiple-choice trivia question based *only* on the following text. The question should be specific, answerable from the text, and not require outside knowledge. Provide the question, 4 distinct answer choices (A, B, C, D) where only one is correct according to the text, and indicate the correct answer letter. Format the output *exactly* like this, with each part on a new line:\n\nQuestion: [Your question here]\nA) [Choice A]\nB) [Choice B]\nC) [Choice C]\nD) [Choice D]\nCorrect Answer: [Correct Letter (A, B, C, or D)]\n\nText:\n{text_to_send}"""
    try:
        response = model.generate_content(prompt); content = response.text.strip()
        lines = [line.strip() for line in content.split('\n') if line.strip()]; question = None; options = {}; correct_answer_letter = None
        if not lines: print("Parsing Error: No non-empty lines."); return None,None,None
        if not lines[0].startswith("Question:"): print(f"Parsing Error: No 'Question:'. Line: '{lines[0]}'"); return None,None,None
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
        print("Successfully parsed Gemini response."); return question, options, correct_answer_letter
    except Exception as e: print(f"Error in Gemini Q gen: {e}"); return None,None,None

def calculate_brier_score(confidence, is_correct):
    probability = confidence / 100.0; outcome = 1.0 if is_correct else 0.0
    return (probability - outcome)**2

# --- NEW: Session Stats Initialization Helper ---
def initialize_session_stats():
    """Helper to initialize or ensure all stat keys exist in session['stats']."""
    default_stats = {
        'total_answered': 0,        # Overall lifetime for the browser session
        'total_correct': 0,         # Overall lifetime for the browser session
        'brier_scores': [],         # Accumulates for the entire session (for "Session" Brier)
        'game_brier_scores': [],    # For the current game (for "Game" Brier)
        'confidence_levels': [],    # For the current game's calibration chart
        'correctness': [],          # For the current game's calibration chart
        'cumulative_score': 0.0,    # For the current game
        'questions_this_game': 0,   # For the current game
        'games_played_session': 0,  # NEW: Number of games completed in this session
        'completed_game_scores_session': [] # NEW: List of scores for completed games in this session
    }
    if 'stats' not in session:
        session['stats'] = default_stats.copy()
        print("New session: Initialized all stats.")
    else:
        # Ensure all keys exist for potentially older sessions
        updated = False
        for key, default_val in default_stats.items():
            if key not in session['stats']:
                session['stats'][key] = default_val
                updated = True
        if updated:
            print("Existing session: Ensured all stat keys are present.")
    session.modified = True # Important to save changes if any were made

# --- Routes ---
@app.route('/')
def index():
    initialize_session_stats() # Ensures all keys are set up
    active_question_data = session.get('current_question') # For re-display on refresh (Point c)
    # No need to pass session['stats'] here, fetchStats will get it with game_length
    return render_template('index.html', active_question_data=active_question_data)

@app.route('/get_trivia_question', methods=['GET'])
def get_trivia_question():
    # ... (route logic remains the same as your version) ...
    min_summary_words = get_setting('min_summary_words', 50); gemini_context_length = get_setting('gemini_context_length', 3000); page_selection_strategy = get_setting('page_selection_strategy', 'random').lower()
    search_keywords = get_setting('search_keywords', 'History, Science, Technology, Art, Geography, Culture, Philosophy, Sports'); target_categories = get_setting('target_categories', 'Physics, World_War_II, Cities_in_France, Mammals, Programming_languages'); api_result_limit = get_setting('api_result_limit', 20)
    print(f"\n--- Requesting new question ---\nUsing settings: Strategy='{page_selection_strategy}', MinWords={min_summary_words}, ContextLen={gemini_context_length}, Limit={api_result_limit}")
    page = None; question = None; options = None; correct_answer = None; wiki_page_title = None; wiki_page_url = None; generation_attempt = 0
    while generation_attempt < MAX_GENERATION_ATTEMPTS:
        generation_attempt += 1; print(f"\nOverall Generation Attempt {generation_attempt}/{MAX_GENERATION_ATTEMPTS}")
        page = get_wikipedia_page(page_selection_strategy, search_keywords, target_categories, api_result_limit)
        if not page: print("Failed to get page. Continuing attempt loop."); continue
        wiki_page_title = page.title; wiki_page_url = page.fullurl; summary = page.summary
        print(f"Attempting Q for: {wiki_page_title}\nSummary length: {len(summary)} chars, ~{len(summary.split())} words.")
        if len(summary.split()) < min_summary_words: print(f"Summary too short. Trying new page."); page = None; continue
        question, options, correct_answer = generate_question_from_text(summary, gemini_context_length)
        if question and options and correct_answer: print(f"Generated Q for '{wiki_page_title}'."); break
        else: print(f"Failed Q gen for '{wiki_page_title}'. Trying new page."); page = None;
    if not (page and question and options and correct_answer): print(f"Failed Q gen after {MAX_GENERATION_ATTEMPTS} attempts."); return jsonify({"error": f"Failed Q gen after {MAX_GENERATION_ATTEMPTS} attempts."}), 503
    session['current_question'] = {'title': wiki_page_title, 'url': wiki_page_url, 'question': question, 'options': options, 'correct_answer_letter': correct_answer}
    session.modified = True; print(f"Sending Q: {question}"); return jsonify({'question': question, 'options': options, 'wiki_page_title': wiki_page_title, 'wiki_page_url': wiki_page_url})

@app.route('/submit_answer', methods=['POST'])
def submit_answer():
    initialize_session_stats() # Ensure structure before use
    data = request.get_json()
    user_answer_letter = data.get('answer'); user_confidence = data.get('confidence')
    if 'current_question' not in session: return jsonify({"error": "No active question."}), 400
    if user_answer_letter is None or user_confidence is None: return jsonify({"error": "Missing answer/confidence."}), 400
    try: user_confidence = int(user_confidence); assert 0 <= user_confidence <= 100
    except (ValueError, AssertionError): return jsonify({"error": "Invalid confidence."}), 400

    current_q = session['current_question']
    correct_answer_letter = current_q['correct_answer_letter']
    correct_answer_text = current_q['options'].get(correct_answer_letter)
    is_correct = (user_answer_letter == correct_answer_letter)
    brier_score = calculate_brier_score(user_confidence, is_correct)
    points = 0.0
    try:
        base_correct = float(get_setting('score_base_correct', 10.0)); mult_correct = float(get_setting('score_mult_correct', 0.9))
        base_incorrect = float(get_setting('score_base_incorrect', -100.0)); mult_incorrect = float(get_setting('score_mult_incorrect', 0.9))
        if is_correct: points = base_correct + (mult_correct * user_confidence)
        else: points = base_incorrect + (mult_incorrect * (100 - user_confidence))
        points = round(points, 2); print(f"Calculated score: {points}")
    except Exception as e: print(f"Error calculating score: {e}"); points = 0.0

    stats = session['stats']
    stats['total_answered'] += 1
    if is_correct: stats['total_correct'] += 1
    stats['brier_scores'].append(brier_score)       # Session Brier
    stats['game_brier_scores'].append(brier_score)  # Game Brier
    stats['confidence_levels'].append(user_confidence) # For per-game calibration chart
    stats['correctness'].append(is_correct)       # For per-game calibration chart
    stats['cumulative_score'] += points
    stats['cumulative_score'] = round(stats['cumulative_score'], 2)
    stats['questions_this_game'] += 1

    game_length = int(get_setting('game_length', 20)); end_of_game = False
    if stats['questions_this_game'] >= game_length:
        end_of_game = True
        stats['completed_game_scores_session'].append(stats['cumulative_score']) # For Point b
        print(f"Game ended. Qs: {stats['questions_this_game']}, Score: {stats['cumulative_score']}")

    # session['stats'] = stats # Assign back to session
    current_session_stats = session['stats'].copy()
    current_session_stats['game_length_setting'] = int(get_setting('game_length', 20))
    session.pop('current_question', None)
    session.modified = True

    try:
        response_entry = Response(session_id=session.sid if hasattr(session,'sid') else request.remote_addr, wiki_page_title=current_q['title'], question_text=current_q['question'], answer_options=str(current_q['options']), correct_answer=correct_answer_letter, user_answer=user_answer_letter, user_confidence=user_confidence, is_correct=is_correct, brier_score=brier_score, points_awarded=points)
        db.session.add(response_entry); db.session.commit(); print(f"Response saved. ID: {response_entry.id}, Points: {points}")
    except Exception as e: db.session.rollback(); print(f"Error saving response: {e}")

    return jsonify({"result": "correct" if is_correct else "incorrect", "correct_answer": correct_answer_letter, "correct_answer_text": correct_answer_text, "brier_score": round(brier_score, 3), "points_awarded": points, "new_stats": current_session_stats, "end_of_game": end_of_game })

@app.route('/get_stats')
def get_stats():
    initialize_session_stats() # Ensures all keys are set up
    current_stats = session['stats'].copy()
    current_stats['game_length_setting'] = int(get_setting('game_length', 20))
    return jsonify(current_stats)

@app.route('/get_calibration_data')
def get_calibration_data():
    initialize_session_stats() # Ensures keys like confidence_levels exist
    stats = session['stats']
    # For per-game chart, confidence_levels and correctness are reset in start_new_game
    if not stats.get('confidence_levels'): return jsonify({"points": []})
    confidence_levels = stats['confidence_levels']; correctness = stats['correctness']
    num_bins = 10; counts = [0] * num_bins; correct_counts = [0] * num_bins; sum_confidence_per_bin = [0.0] * num_bins
    if not confidence_levels: return jsonify({"points": []})
    for conf, correct in zip(confidence_levels, correctness):
        conf = int(conf);
        if conf < 0 or conf > 100: continue
        bin_index = min(conf // (100 // num_bins), num_bins - 1)
        counts[bin_index] += 1; sum_confidence_per_bin[bin_index] += conf
        if correct: correct_counts[bin_index] += 1
    chart_points = []
    for i in range(num_bins):
        if counts[i] > 0:
            avg_confidence = sum_confidence_per_bin[i] / counts[i]
            accuracy = correct_counts[i] / counts[i]
            chart_points.append({'x': avg_confidence, 'y': accuracy, 'count': counts[i]})
    return jsonify({'points': chart_points})

@app.route('/start_new_game', methods=['POST'])
def start_new_game():
    initialize_session_stats() # Ensure all keys are present before selective reset
    stats = session['stats']
    stats['games_played_session'] += 1 # For Point b
    # Reset items for the new game
    stats['cumulative_score'] = 0.0
    stats['questions_this_game'] = 0
    stats['game_brier_scores'] = []
    stats['confidence_levels'] = [] # Reset for per-game calibration chart
    stats['correctness'] = []     # Reset for per-game calibration chart
    session['stats'] = stats
    session.modified = True
    print("New game started, session stats reset for game-specific items.")
    current_stats_payload = session['stats'].copy()
    current_stats_payload['game_length_setting'] = int(get_setting('game_length', 20))
    return jsonify({"status": "success", "new_stats": current_stats_payload})

# --- Main Execution & DB Initialization ---
if __name__ == '__main__':
    with app.app_context():
        print("Ensuring database tables exist..."); db.create_all(); print("Tables checked/created.")
        print("Checking for default AppSettings...")
        defaults = {
            'min_summary_words': ('50', 'Minimum words in Wikipedia summary to attempt question generation'),
            'gemini_context_length': ('3000', 'Max characters of summary sent to Gemini API'),
            'page_selection_strategy': ('random', 'Method to select Wikipedia pages (random, search, category)'),
            'search_keywords': ('History, Science, Technology, Art, Geography, Culture, Philosophy, Sports', 'Comma-separated keywords for search strategy'),
            'target_categories': ('Physics, World_War_II, Cities_in_France, Mammals, Programming_languages', 'Comma-separated categories for category strategy (no "Category:" prefix)'),
            'api_result_limit': ('20', 'Max results to fetch/consider from search/category API calls'),
            'score_base_correct': ('10', 'Base points for correct answer at 0% confidence'),
            'score_mult_correct': ('0.9', 'Additional points per confidence % for correct answer (e.g., 0.9*conf)'),
            'score_base_incorrect': ('-100', 'Base points (penalty) for incorrect answer at 100% confidence'),
            'score_mult_incorrect': ('0.9', 'Reduction in penalty per confidence % *below* 100 for incorrect answer (e.g., base + 0.9*(100-conf))'),
            'game_length': ('20', 'Number of questions per game session') # Confirm this default
        }
        added_defaults = False
        for key, (value, desc) in defaults.items():
            exists = AppSetting.query.filter_by(setting_key=key).first()
            if not exists:
                print(f"Adding default setting: {key} = {value}"); setting = AppSetting(setting_key=key, setting_value=value, description=desc)
                db.session.add(setting); added_defaults = True
        if added_defaults: db.session.commit(); print("Default settings committed.")
        else: print("All default settings already exist.")
    print("Starting Flask application..."); app.run(debug=True, host='0.0.0.0', port=5000)