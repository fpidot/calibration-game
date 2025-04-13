# app.py

import os
import random
import requests
import math
from flask import Flask, render_template, request, jsonify, session
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
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') # Ensure SECRET_KEY is in your .env

# --- Database Setup ---
# Import db instance from models.py where it's defined (db = SQLAlchemy())
from models import db
# Initialize db with the Flask app context AFTER app is created
db.init_app(app)

# Setup Flask-Migrate AFTER db is initialized with app
migrate = Migrate(app, db)

# --- Database Models ---
# Import specific models AFTER db is initialized with app
# This import should now work because models.py exists and db is handled correctly
from models import Response, AppSetting

# --- Admin Setup ---
# Import admin views AFTER models are defined/imported
from admin_views import AppSettingAdminView
admin = Admin(app, name='Trivia Admin', template_mode='bootstrap3')
# Pass the specific Model class (AppSetting) and the db.session
admin.add_view(AppSettingAdminView(AppSetting, db.session))

# --- Wikipedia API Setup ---
wiki_user_agent_contact = os.getenv('WIKI_USER_AGENT_CONTACT', 'your_email@example.com')
# Define the user agent string separately
WIKI_USER_AGENT = f'WikipediaTriviaGame/1.0 (https://github.com/fpidot/calibration-game; {wiki_user_agent_contact})'
# Use the string when initializing wikipediaapi
wiki_wiki = wikipediaapi.Wikipedia(
    user_agent=WIKI_USER_AGENT,
    language='en'
)

# --- Gemini API Setup ---
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
model = None # Initialize model to None
if not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY environment variable not set.")
    # Consider how the app should behave - maybe run without Q generation?
else:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash') # Or your preferred model
        print("Gemini API configured successfully.")
    except Exception as e:
        print(f"Error configuring Gemini API: {e}")
        # Model remains None

# --- Constants ---
PAGE_FETCH_ATTEMPTS = 5 # Max attempts to find a suitable Wikipedia page via API calls
MAX_GENERATION_ATTEMPTS = 3 # Max attempts to generate a question from a fetched page

# --- Helper Functions ---

def get_setting(key, default_value):
    """Fetches a setting from the AppSetting table, returning default if not found or conversion fails."""
    # Ensure this runs within app context if called outside request scope, but here it's fine.
    setting = AppSetting.query.filter_by(setting_key=key).first()
    if setting and setting.setting_value is not None:
        try:
            value_type = type(default_value)
            if value_type is bool:
                val = setting.setting_value.lower().strip()
                if val in ('true', '1'): return True
                elif val in ('false', '0'): return False
                else:
                    print(f"Warning: Non-boolean value '{setting.setting_value}' found for bool setting '{key}'. Using default.")
                    return default_value
            else: # Works for int, float, str
                return value_type(setting.setting_value)
        except (ValueError, TypeError) as e:
            print(f"Warning: Could not convert value '{setting.setting_value}' for setting '{key}' to type {value_type}. Error: {e}. Using default.")
            return default_value
    return default_value

def get_wikipedia_page(strategy, keywords_str, categories_str, limit):
    """Gets a Wikipedia page object based on the selected strategy."""
    selected_title = None
    attempts = 0
    while attempts < PAGE_FETCH_ATTEMPTS:
        attempts += 1
        print(f"Page Fetch Attempt {attempts}/{PAGE_FETCH_ATTEMPTS} using strategy: {strategy}")
        current_strategy = strategy
        try:
            if current_strategy == 'search':
                keywords = [k.strip() for k in keywords_str.split(',') if k.strip()]
                if not keywords:
                    print("Warning: Search strategy selected but no keywords defined. Falling back to random.")
                    current_strategy = 'random'
                else:
                    keyword = random.choice(keywords)
                    print(f"Searching with keyword: {keyword}")
                    S = requests.Session()
                    URL = "https://en.wikipedia.org/w/api.php"
                    PARAMS = {"action": "query","format": "json","list": "search","srsearch": keyword,"srnamespace": "0","srlimit": limit,"srwhat": "text"}
                    headers = {'User-Agent': WIKI_USER_AGENT}
                    R = S.get(url=URL, params=PARAMS, headers=headers)
                    R.raise_for_status(); data = R.json()
                    search_results = data.get("query", {}).get("search", [])
                    if search_results:
                        selected_title = random.choice(search_results)['title']
                        print(f"Selected '{selected_title}' from search results.")
                    else: print(f"No search results found for keyword '{keyword}'. Retrying strategy."); continue
            elif current_strategy == 'category':
                categories = [c.strip() for c in categories_str.split(',') if c.strip()]
                if not categories:
                    print("Warning: Category strategy selected but no categories defined. Falling back to random.")
                    current_strategy = 'random'
                else:
                    category_name_base = random.choice(categories)
                    category_name = category_name_base if category_name_base.lower().startswith("category:") else f"Category:{category_name_base}"
                    print(f"Fetching members for category: {category_name}")
                    S = requests.Session(); URL = "https://en.wikipedia.org/w/api.php"
                    PARAMS = {"action": "query","format": "json","list": "categorymembers","cmtitle": category_name,"cmlimit": limit,"cmtype": "page","cmprop": "title"}
                    headers = {'User-Agent': WIKI_USER_AGENT}
                    R = S.get(url=URL, params=PARAMS, headers=headers)
                    R.raise_for_status(); data = R.json()
                    members = data.get("query", {}).get("categorymembers", [])
                    if members:
                        selected_title = random.choice(members)['title']
                        print(f"Selected '{selected_title}' from category members.")
                    else: print(f"No page members found in category '{category_name}'. Retrying strategy."); continue
            if current_strategy == 'random' or (selected_title is None and current_strategy != 'random'):
                print("Using random strategy or falling back to random.")
                S = requests.Session(); URL = "https://en.wikipedia.org/w/api.php"
                PARAMS = {"action": "query","format": "json","list": "random","rnnamespace": "0","rnlimit": "1"}
                headers = {'User-Agent': WIKI_USER_AGENT}
                R = S.get(url=URL, params=PARAMS, headers=headers)
                R.raise_for_status(); data = R.json()
                random_pages = data.get("query", {}).get("random", [])
                if random_pages: selected_title = random_pages[0]["title"]; print(f"Selected random page: {selected_title}")
                else: print("Could not fetch random page title via API. Retrying strategy."); continue
            if selected_title:
                print(f"Fetching page content for: {selected_title}")
                page = wiki_wiki.page(selected_title)
                if page and page.exists():
                    summary_lower = page.summary.lower()
                    min_summary_words_check = get_setting('min_summary_words', 50)
                    is_disambiguation = "may refer to:" in summary_lower or page.title.lower().endswith("(disambiguation)")
                    is_stub = len(page.sections) <= 1 and len(summary_lower.split()) < max(10, min_summary_words_check // 2) # Stricter stub check
                    if is_disambiguation: print(f"Page '{selected_title}' seems to be a disambiguation page. Retrying strategy."); selected_title = None; continue
                    if is_stub: print(f"Page '{selected_title}' seems to be a stub (too short). Retrying strategy."); selected_title = None; continue
                    print(f"Successfully fetched and validated page: {page.title}")
                    return page
                else: print(f"Page '{selected_title}' does not exist or could not be fetched by wikipediaapi. Retrying strategy."); selected_title = None
        except requests.exceptions.RequestException as e: print(f"Network or API error during page fetch: {e}. Retrying strategy."); selected_title = None
        except Exception as e: print(f"An unexpected error occurred during page fetch: {e}. Retrying strategy."); selected_title = None
    print(f"Failed to find a suitable Wikipedia page after {PAGE_FETCH_ATTEMPTS} attempts.")
    return None

def generate_question_from_text(text, context_length):
    """Generates a multiple-choice question from text using the Gemini API."""
    if not text: print("Error: Cannot generate question from empty text."); return None, None, None
    if model is None: print("Error: Gemini model not available or not configured."); return None, None, None # Check if model exists

    text_to_send = text[:context_length]
    prompt = f"""Create a multiple-choice trivia question based *only* on the following text. The question should be specific, answerable from the text, and not require outside knowledge. Provide the question, 4 distinct answer choices (A, B, C, D) where only one is correct according to the text, and indicate the correct answer letter. Format the output *exactly* like this, with each part on a new line:

Question: [Your question here]
A) [Choice A]
B) [Choice B]
C) [Choice C]
D) [Choice D]
Correct Answer: [Correct Letter (A, B, C, or D)]

Text:
{text_to_send}
"""
    try:
        response = model.generate_content(prompt)

        # --- Robust Parsing ---
        content = response.text.strip()
        # Filter out empty lines AFTER splitting
        lines = [line.strip() for line in content.split('\n') if line.strip()] # <-- Filter empty lines

        question = None
        options = {}
        correct_answer_letter = None
        correct_answer_line_index = -1 # Keep track of where Correct Answer line is

        if not lines:
             print("Parsing Error: No non-empty lines found in Gemini response.")
             return None, None, None

        # Find the Question line
        if lines[0].startswith("Question:"):
            question = lines[0][len("Question:"):].strip()
        else:
            print(f"Parsing Error: First line doesn't start with 'Question:'. Line: '{lines[0]}'")
            return None, None, None # Expect Question first

        # Find the Options (expecting 4 lines starting with A), B), C), D) after Question)
        option_prefixes = ['A)', 'B)', 'C)', 'D)']
        temp_options = {}
        option_lines_found = 0
        # Start searching from the line *after* the question
        current_line_index = 1
        while option_lines_found < 4 and current_line_index < len(lines):
             line = lines[current_line_index]
             expected_prefix = option_prefixes[option_lines_found]
             if line.startswith(expected_prefix):
                 temp_options[expected_prefix[0]] = line[len(expected_prefix):].strip()
                 option_lines_found += 1
             # Allow skipping lines that don't match expected option format
             # else:
             #     print(f"Debug: Skipping line '{line}', expecting '{expected_prefix}'")
             current_line_index += 1

        if option_lines_found == 4:
             options = temp_options
        else:
             print(f"Parsing Error: Didn't find all 4 options (A, B, C, D). Found {option_lines_found}.")
             # Log received lines for debugging
             print("Received lines for parsing:", lines)
             return None, None, None # Expect 4 options

        # Find the Correct Answer line (can appear after options)
        # current_line_index now points to the line *after* the last processed line (likely after D)
        while current_line_index < len(lines):
            line = lines[current_line_index]
            if line.startswith("Correct Answer:"):
                correct_answer_letter = line[len("Correct Answer:"):].strip().upper()
                # Validate the letter is one of the options
                if correct_answer_letter not in options:
                    print(f"Parsing Error: Correct Answer letter '{correct_answer_letter}' not in parsed options keys {list(options.keys())}.")
                    correct_answer_letter = None # Invalidate
                break # Found the correct answer line
            current_line_index += 1 # Move to next line

        if not correct_answer_letter:
             print("Parsing Error: 'Correct Answer:' line not found or letter invalid after options.")
             print("Received lines for parsing:", lines)
             return None, None, None

        # Final Check: Ensure we have everything needed
        if not all([question, options, correct_answer_letter]):
            print(f"Error: Failed final check after parsing Gemini response.")
            return None, None, None

        print("Successfully parsed Gemini response.")
        return question, options, correct_answer_letter

    except Exception as e:
        print(f"Error generating question or parsing response with Gemini: {e}")
        return None, None, None

def calculate_brier_score(confidence, is_correct):
    """Calculates the Brier score for a single prediction."""
    probability = confidence / 100.0; outcome = 1.0 if is_correct else 0.0
    return (probability - outcome)**2

# --- Routes ---

@app.route('/')
def index():
    if 'stats' not in session:
        session['stats'] = {'total_answered': 0, 'total_correct': 0, 'brier_scores': [], 'confidence_levels': [], 'correctness': []}
    for key in ['brier_scores', 'confidence_levels', 'correctness']:
        if key not in session['stats']: session['stats'][key] = []
    session.modified = True
    return render_template('index.html', stats=session['stats'])

@app.route('/get_trivia_question', methods=['GET'])
def get_trivia_question():
    min_summary_words = get_setting('min_summary_words', 50)
    gemini_context_length = get_setting('gemini_context_length', 3000)
    page_selection_strategy = get_setting('page_selection_strategy', 'random').lower()
    search_keywords = get_setting('search_keywords', 'History, Science, Technology, Art, Geography, Culture, Philosophy, Sports')
    target_categories = get_setting('target_categories', 'Physics, World_War_II, Cities_in_France, Mammals, Programming_languages')
    api_result_limit = get_setting('api_result_limit', 20)

    print(f"\n--- Requesting new question ---")
    print(f"Using settings: Strategy='{page_selection_strategy}', MinWords={min_summary_words}, ContextLen={gemini_context_length}, Limit={api_result_limit}")

    page = None; question = None; options = None; correct_answer = None
    wiki_page_title = None; wiki_page_url = None
    generation_attempt = 0

    while generation_attempt < MAX_GENERATION_ATTEMPTS:
        generation_attempt += 1
        print(f"\nOverall Generation Attempt {generation_attempt}/{MAX_GENERATION_ATTEMPTS}")
        page = get_wikipedia_page(page_selection_strategy, search_keywords, target_categories, api_result_limit)
        if not page:
            print("Failed to get suitable page in get_wikipedia_page. Aborting this attempt.")
            continue # Try the main generation loop again to fetch another page

        wiki_page_title = page.title; wiki_page_url = page.fullurl
        summary = page.summary
        print(f"Attempting to generate question for: {wiki_page_title}")
        print(f"Summary length: {len(summary)} chars, ~{len(summary.split())} words.")

        if len(summary.split()) < min_summary_words:
            print(f"Summary too short ({len(summary.split())} words < {min_summary_words}). Trying new page.")
            page = None; continue # Try the main generation loop again

        question, options, correct_answer = generate_question_from_text(summary, gemini_context_length)
        if question and options and correct_answer:
            print(f"Successfully generated question for '{wiki_page_title}'.")
            break # Exit loop, success!
        else:
            print(f"Failed to generate valid Q&A from summary of '{wiki_page_title}'. Trying new page.")
            page = None; continue # Try the main generation loop again

    if not (page and question and options and correct_answer):
        print(f"Failed to generate a question after {MAX_GENERATION_ATTEMPTS} attempts.")
        return jsonify({"error": f"Failed to generate a trivia question after {MAX_GENERATION_ATTEMPTS} attempts."}), 503 # Service Unavailable or 500

    session['current_question'] = {
        'title': wiki_page_title, 'url': wiki_page_url, 'question': question,
        'options': options, 'correct_answer_letter': correct_answer
    }
    session.modified = True
    print(f"Sending question to client: {question}")
    return jsonify({
        'question': question, 'options': options,
        'wiki_page_title': wiki_page_title, 'wiki_page_url': wiki_page_url
    })

@app.route('/submit_answer', methods=['POST'])
def submit_answer():
    data = request.get_json()
    user_answer_letter = data.get('answer')
    user_confidence = data.get('confidence')

    if 'current_question' not in session: return jsonify({"error": "No active question found in session."}), 400
    if user_answer_letter is None or user_confidence is None: return jsonify({"error": "Missing answer or confidence."}), 400

    try:
        user_confidence = int(user_confidence)
        if not (0 <= user_confidence <= 100): raise ValueError("Confidence out of range")
    except ValueError: return jsonify({"error": "Invalid confidence value."}), 400

    current_q = session['current_question']
    correct_answer_letter = current_q['correct_answer_letter']
    correct_answer_text = current_q['options'].get(correct_answer_letter)
    is_correct = (user_answer_letter == correct_answer_letter)
    brier_score = calculate_brier_score(user_confidence, is_correct)

    if 'stats' not in session: # Initialize just in case
        session['stats'] = {'total_answered': 0, 'total_correct': 0, 'brier_scores': [], 'confidence_levels': [], 'correctness': []}
        for key in ['brier_scores', 'confidence_levels', 'correctness']:
             if key not in session['stats']: session['stats'][key] = []

    session['stats']['total_answered'] += 1
    if is_correct: session['stats']['total_correct'] += 1
    session['stats']['brier_scores'].append(brier_score)
    session['stats']['confidence_levels'].append(user_confidence)
    session['stats']['correctness'].append(is_correct)

    # Store response in database
    try:
        response_entry = Response(
            session_id=session.sid if hasattr(session, 'sid') else request.remote_addr,
            wiki_page_title=current_q['title'], question_text=current_q['question'],
            answer_options=str(current_q['options']), correct_answer=correct_answer_letter,
            user_answer=user_answer_letter, user_confidence=user_confidence,
            is_correct=is_correct, brier_score=brier_score
            # timestamp is handled by default=datetime.utcnow in model
        )
        db.session.add(response_entry)
        db.session.commit()
        print(f"Response saved to DB. ID: {response_entry.id}")
    except Exception as e:
        db.session.rollback()
        print(f"Error saving response to database: {e}")
        # Decide if this should be a user-facing error or just logged

    session.pop('current_question', None)
    session.modified = True

    return jsonify({
        "result": "correct" if is_correct else "incorrect",
        "correct_answer": correct_answer_letter, "correct_answer_text": correct_answer_text,
        "brier_score": round(brier_score, 3),
        "new_stats": session['stats']
    })

@app.route('/get_stats')
def get_stats():
    """Returns the current session statistics."""
    # Ensure stats exist in session, providing defaults if not
    if 'stats' not in session:
        session['stats'] = {'total_answered': 0, 'total_correct': 0, 'brier_scores': [], 'confidence_levels': [], 'correctness': []}
        for key in ['brier_scores', 'confidence_levels', 'correctness']: # Ensure lists exist
             if key not in session['stats']: session['stats'][key] = []
        session.modified = True
    return jsonify(session['stats'])

@app.route('/get_calibration_data')
def get_calibration_data():
    """Returns data formatted for the calibration chart."""
    if 'stats' not in session or not session['stats']['confidence_levels']:
        return jsonify({"bins": [], "accuracy": [], "count": []}) # Return empty data if no stats

    stats = session['stats']
    confidence_levels = stats['confidence_levels']
    correctness = stats['correctness'] # List of booleans

    # Group data into bins (e.g., 0-10, 11-20, ..., 91-100)
    # Or maybe simpler 10% bins: 0-9, 10-19, ... 90-100
    num_bins = 10
    bins = [[] for _ in range(num_bins)]
    counts = [0] * num_bins
    correct_counts = [0] * num_bins

    for conf, correct in zip(confidence_levels, correctness):
        if conf == 100: # Put 100 in the last bin
            bin_index = num_bins - 1
        else:
            bin_index = conf // (100 // num_bins) # e.g., 75 // 10 = 7 -> bin index 7 (70-79)

        # Simple binning by 10s (0-9, 10-19, ..., 90-100)
        #bin_index = min(conf // 10, num_bins - 1)

        counts[bin_index] += 1
        if correct:
            correct_counts[bin_index] += 1

    # Calculate accuracy for each bin (avoid division by zero)
    accuracy = [
        (correct_counts[i] / counts[i]) if counts[i] > 0 else 0
        for i in range(num_bins)
    ]

    # Prepare bin labels for the chart (e.g., "0-10%", "10-20%", ...)
    bin_labels = [f"{i * (100 // num_bins)}-{(i + 1) * (100 // num_bins)}%" for i in range(num_bins)]
    # Adjust last label for 90-100% or similar depending on exact binning
    bin_labels[-1] = f"{ (num_bins - 1) * (100 // num_bins) }-100%"


    # Return data in a format Chart.js can use
    # We need average confidence *within* each bin, and accuracy *for* that bin
    # Let's recalculate slightly for a better plot: plot accuracy vs average confidence per bin

    avg_confidence_per_bin = [0] * num_bins
    for conf, correct in zip(confidence_levels, correctness):
         if conf == 100: bin_index = num_bins - 1
         else: bin_index = conf // (100 // num_bins)
         avg_confidence_per_bin[bin_index] += conf

    # Calculate average confidence only for bins with data
    for i in range(num_bins):
        if counts[i] > 0:
            avg_confidence_per_bin[i] /= counts[i]
        else:
            avg_confidence_per_bin[i] = (i * (100 // num_bins) + (i + 1) * (100 // num_bins)) / 2 # Estimate center if empty


    # Data for Chart.js: plot points (average_confidence, accuracy) for each bin
    chart_data = {
        'points': [
            {'x': avg_confidence_per_bin[i], 'y': accuracy[i], 'count': counts[i]}
            for i in range(num_bins) if counts[i] > 0 # Only include bins with data
        ]
        # 'labels': bin_labels # Could also send labels if needed by chart
    }

    return jsonify(chart_data)

# --- Main Execution & DB Initialization ---
if __name__ == '__main__':
    with app.app_context():
        # Ensure all tables defined in models are created if they don't exist
        # This is okay for development, but migrations are better for production changes
        print("Ensuring database tables exist...")
        db.create_all()
        print("Tables checked/created.")

        # Check and add default AppSetting entries if they are missing
        print("Checking for default AppSettings...")
        defaults = {
            'min_summary_words': ('50', 'Minimum words in Wikipedia summary to attempt question generation'),
            'gemini_context_length': ('3000', 'Max characters of summary sent to Gemini API'),
            'page_selection_strategy': ('random', 'Method to select Wikipedia pages (random, search, category)'),
            'search_keywords': ('History, Science, Technology, Art, Geography, Culture, Philosophy, Sports', 'Comma-separated keywords for search strategy'),
            'target_categories': ('Physics, World_War_II, Cities_in_France, Mammals, Programming_languages', 'Comma-separated categories for category strategy (no "Category:" prefix)'),
            'api_result_limit': ('20', 'Max results to fetch/consider from search/category API calls')
        }
        added_defaults = False
        for key, (value, desc) in defaults.items():
            exists = AppSetting.query.filter_by(setting_key=key).first()
            if not exists:
                print(f"Adding default setting: {key} = {value}")
                setting = AppSetting(setting_key=key, setting_value=value, description=desc)
                db.session.add(setting)
                added_defaults = True
        if added_defaults:
            db.session.commit()
            print("Default settings committed.")
        else:
            print("All default settings already exist.")

    print("Starting Flask application...")
    # Use debug=False in production! Host='0.0.0.0' makes it accessible on your network.
app.run(debug=True, host='0.0.0.0', port=5000)