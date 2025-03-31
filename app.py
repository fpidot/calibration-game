import sys
print("Python sys.path:", sys.path)
import os
import random
import requests # <-- Added
import math # <-- Added for Brier score calculation if needed, safe to keep
from flask import Flask, render_template, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from dotenv import load_dotenv
import google.generativeai as genai
import wikipediaapi # <-- Changed from 'wikipedia'

# --- App Configuration ---
load_dotenv()
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') # Ensure SECRET_KEY is in your .env

# --- Database Setup ---
# Assuming db initialization is needed here before models are imported/used
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- Database Models ---
# Import models AFTER db is initialized
# This structure assumes models.py defines models using this 'db' instance
from models import Response, AppSetting

# --- Admin Setup ---
# Import admin views AFTER models are defined/imported
from admin_views import AppSettingAdminView
admin = Admin(app, name='Trivia Admin', template_mode='bootstrap3')
admin.add_view(AppSettingAdminView(AppSetting, db.session))

# --- Wikipedia API Setup ---
# Use a specific user agent as recommended by MediaWiki API guidelines
wiki_wiki = wikipediaapi.Wikipedia(
    user_agent='WikipediaTriviaGame/1.0 (https://github.com/fpidot/calibration-game; please add contact info in code or env)', # Replace placeholder contact
    language='en'
)

# --- Gemini API Setup ---
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY environment variable not set.")
    # Handle this case appropriately - maybe exit or disable Gemini features
else:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-1.5-flash') # Or your preferred model
    except Exception as e:
        print(f"Error configuring Gemini API: {e}")
        # Handle initialization error

# --- Constants ---
MAX_TOKENS = 1000 # Example value for potential future use with other models, not directly used by Gemini helper
PAGE_FETCH_ATTEMPTS = 5 # Max attempts to find a suitable Wikipedia page via API calls
MAX_GENERATION_ATTEMPTS = 3 # Max attempts to generate a question from a fetched page

# --- Helper Functions ---

def get_setting(key, default_value):
    """Fetches a setting from the AppSetting table, returning default if not found or conversion fails."""
    setting = AppSetting.query.filter_by(setting_key=key).first()
    if setting and setting.setting_value is not None:
        # Attempt to convert to the type of the default_value
        try:
            value_type = type(default_value)
            if value_type is bool:
                # Handle boolean conversion ('true', 'false', '1', '0')
                val = setting.setting_value.lower().strip()
                if val in ('true', '1'):
                    return True
                elif val in ('false', '0'):
                    return False
                else: # Fallback if value is not clearly boolean
                    print(f"Warning: Non-boolean value '{setting.setting_value}' found for boolean setting '{key}'. Using default.")
                    return default_value
            else: # Works for int, float, str
                return value_type(setting.setting_value)
        except (ValueError, TypeError) as e:
            print(f"Warning: Could not convert value '{setting.setting_value}' for setting '{key}' to type {value_type}. Error: {e}. Using default.")
            return default_value # Return default if conversion fails
    # print(f"Setting '{key}' not found or value is None. Using default: {default_value}")
    return default_value

# Function to get Wikipedia page using different strategies
def get_wikipedia_page(strategy, keywords_str, categories_str, limit):
    """
    Gets a Wikipedia page object based on the selected strategy.
    Retries fetching different pages up to PAGE_FETCH_ATTEMPTS times if issues occur.
    Returns a wikipediaapi.WikipediaPage object or None if unsuccessful.
    """
    selected_title = None
    attempts = 0

    while attempts < PAGE_FETCH_ATTEMPTS:
        attempts += 1
        print(f"Page Fetch Attempt {attempts}/{PAGE_FETCH_ATTEMPTS} using strategy: {strategy}")
        current_strategy = strategy # Store original strategy in case of fallback

        try:
            # --- Strategy Selection ---
            if current_strategy == 'search':
                keywords = [k.strip() for k in keywords_str.split(',') if k.strip()]
                if not keywords:
                    print("Warning: Search strategy selected but no keywords defined. Falling back to random.")
                    current_strategy = 'random' # Fallback for this attempt
                else:
                    keyword = random.choice(keywords)
                    print(f"Searching with keyword: {keyword}")
                    # Using the underlying MediaWiki search via requests, as wikipediaapi search is basic
                    S = requests.Session()
                    URL = "https://en.wikipedia.org/w/api.php"
                    PARAMS = {
                        "action": "query",
                        "format": "json",
                        "list": "search",
                        "srsearch": keyword,
                        "srnamespace": "0", # Main namespace
                        "srlimit": limit,   # Limit results considered
                        "srwhat": "text"    # Search within page text
                    }
                    headers = {'User-Agent': wiki_wiki.user_agent}
                    R = S.get(url=URL, params=PARAMS, headers=headers)
                    R.raise_for_status()
                    data = R.json()
                    search_results = data.get("query", {}).get("search", [])
                    if search_results:
                        selected_title = random.choice(search_results)['title']
                        print(f"Selected '{selected_title}' from search results.")
                    else:
                        print(f"No search results found for keyword '{keyword}'. Retrying strategy.")
                        continue # Try the while loop again (different keyword potentially)

            elif current_strategy == 'category':
                categories = [c.strip() for c in categories_str.split(',') if c.strip()]
                if not categories:
                    print("Warning: Category strategy selected but no categories defined. Falling back to random.")
                    current_strategy = 'random' # Fallback for this attempt
                else:
                    category_name_base = random.choice(categories)
                    # Ensure 'Category:' prefix
                    category_name = category_name_base if category_name_base.lower().startswith("category:") else f"Category:{category_name_base}"

                    print(f"Fetching members for category: {category_name}")
                    # Using requests for category members
                    S = requests.Session()
                    URL = "https://en.wikipedia.org/w/api.php"
                    PARAMS = {
                        "action": "query",
                        "format": "json",
                        "list": "categorymembers",
                        "cmtitle": category_name,
                        "cmlimit": limit, # Use setting limit
                        "cmtype": "page", # Only get pages, not subcategories
                        "cmprop": "title"
                    }
                    headers = {'User-Agent': wiki_wiki.user_agent}
                    R = S.get(url=URL, params=PARAMS, headers=headers)
                    R.raise_for_status()
                    data = R.json()

                    members = data.get("query", {}).get("categorymembers", [])
                    if members:
                        selected_title = random.choice(members)['title']
                        print(f"Selected '{selected_title}' from category members.")
                    else:
                        print(f"No page members found in category '{category_name}'. Retrying strategy.")
                        continue # Try the while loop again (different category potentially)

            # Default ('random') or fallback strategy
            if current_strategy == 'random' or selected_title is None and current_strategy != 'random':
                print("Using random strategy or falling back to random.")
                S = requests.Session()
                URL = "https://en.wikipedia.org/w/api.php"
                PARAMS = {
                    "action": "query",
                    "format": "json",
                    "list": "random",
                    "rnnamespace": "0", # Namespace 0 is main articles
                    "rnlimit": "1"      # Get 1 random page
                }
                headers = {'User-Agent': wiki_wiki.user_agent}
                R = S.get(url=URL, params=PARAMS, headers=headers)
                R.raise_for_status()
                data = R.json()
                random_pages = data.get("query", {}).get("random", [])
                if random_pages:
                     selected_title = random_pages[0]["title"]
                     print(f"Selected random page: {selected_title}")
                else:
                    print("Could not fetch random page title via API. Retrying strategy.")
                    continue # Try the while loop again

            # --- Page Validation ---
            if selected_title:
                print(f"Fetching page content for: {selected_title}")
                page = wiki_wiki.page(selected_title)
                if page and page.exists():
                    # Check for disambiguation pages or very short stubs
                    summary_lower = page.summary.lower()
                    min_summary_words_check = get_setting('min_summary_words', 50) # Check against setting
                    # Heuristic checks:
                    is_disambiguation = "may refer to:" in summary_lower or page.title.lower().endswith("(disambiguation)")
                    is_stub = len(page.sections) <= 1 and len(summary_lower.split()) < min_summary_words_check // 2 # Crude stub check

                    if is_disambiguation:
                        print(f"Page '{selected_title}' seems to be a disambiguation page. Retrying strategy.")
                        selected_title = None # Reset title to retry loop
                        continue # Try the while loop again
                    if is_stub:
                        print(f"Page '{selected_title}' seems to be a stub (too short). Retrying strategy.")
                        selected_title = None # Reset title to retry loop
                        continue # Try the while loop again

                    # If checks pass, return the valid page object
                    print(f"Successfully fetched and validated page: {page.title}")
                    return page
                else:
                    print(f"Page '{selected_title}' does not exist or could not be fetched by wikipediaapi. Retrying strategy.")
                    selected_title = None # Reset title to retry loop

        except requests.exceptions.RequestException as e:
            print(f"Network or API error during page fetch: {e}. Retrying strategy.")
            selected_title = None # Reset title to retry loop
        except Exception as e: # Catch other potential errors (e.g., JSON parsing, unexpected API response)
            print(f"An unexpected error occurred during page fetch: {e}. Retrying strategy.")
            selected_title = None # Reset title to retry loop

    print(f"Failed to find a suitable Wikipedia page after {PAGE_FETCH_ATTEMPTS} attempts.")
    return None # Failed to get a page after all attempts


def generate_question_from_text(text, context_length):
    """Generates a multiple-choice question from text using the Gemini API."""
    if not text:
        print("Error: Cannot generate question from empty text.")
        return None, None, None

    if 'model' not in globals(): # Check if Gemini model initialized successfully
        print("Error: Gemini model not available.")
        return None, None, None

    text_to_send = text[:context_length] # Use context_length setting

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
        # Use the 'model' instance defined globally
        response = model.generate_content(prompt)

        # --- Robust Parsing ---
        content = response.text.strip()
        lines = content.split('\n')

        question = None
        options = {}
        correct_answer_letter = None

        if len(lines) >= 6:
            if lines[0].startswith("Question:"):
                question = lines[0][len("Question:"):].strip()
            possible_options = lines[1:5]
            option_prefixes = ['A)', 'B)', 'C)', 'D)']
            temp_options = {}
            valid_options = True
            for i, line in enumerate(possible_options):
                prefix = option_prefixes[i]
                if line.startswith(prefix):
                    temp_options[prefix[0]] = line[len(prefix):].strip()
                else:
                    valid_options = False
                    print(f"Parsing Error: Option line '{line}' does not start with expected prefix '{prefix}'.")
                    break # Stop parsing options if format breaks
            if valid_options and len(temp_options) == 4:
                options = temp_options

            if lines[5].startswith("Correct Answer:"):
                 correct_answer_letter = lines[5][len("Correct Answer:"):].strip().upper()
                 # Validate the letter is one of the options
                 if correct_answer_letter not in options:
                     print(f"Parsing Error: Correct Answer letter '{correct_answer_letter}' not in parsed options keys {list(options.keys())}.")
                     correct_answer_letter = None # Invalidate if not A, B, C, or D

        if not all([question, options, correct_answer_letter]):
            print(f"Error: Failed to parse Gemini response reliably. Response received:\n---\n{content}\n---")
            return None, None, None # Return None if parsing failed

        print("Successfully parsed Gemini response.")
        return question, options, correct_answer_letter

    except Exception as e:
        print(f"Error generating question or parsing response with Gemini: {e}")
        # Log the full error potentially
        # Consider checking specific Gemini API error types if the library provides them
        return None, None, None


def calculate_brier_score(confidence, is_correct):
    """Calculates the Brier score for a single prediction."""
    # Confidence is 0-100, convert to 0.0-1.0 probability
    probability = confidence / 100.0
    # Outcome is 1 if correct, 0 if incorrect
    outcome = 1.0 if is_correct else 0.0
    return (probability - outcome)**2

# --- Routes ---

@app.route('/')
def index():
    # Initialize session stats if not present
    if 'stats' not in session:
        session['stats'] = {'total_answered': 0, 'total_correct': 0, 'brier_scores': [], 'confidence_levels': [], 'correctness': []}
    # Ensure lists exist even if counts are 0
    for key in ['brier_scores', 'confidence_levels', 'correctness']:
        if key not in session['stats']:
             session['stats'][key] = []

    # Make sure session changes are saved if we modified it
    session.modified = True
    return render_template('index.html', stats=session['stats'])

@app.route('/get_trivia_question', methods=['GET'])
def get_trivia_question():
    # Get settings from DB with defaults
    min_summary_words = get_setting('min_summary_words', 50)
    gemini_context_length = get_setting('gemini_context_length', 3000)
    page_selection_strategy = get_setting('page_selection_strategy', 'random').lower() # Use lower case
    search_keywords = get_setting('search_keywords', 'History, Science, Technology, Art, Geography, Culture, Philosophy, Sports')
    target_categories = get_setting('target_categories', 'Physics, World_War_II, Cities_in_France, Mammals, Programming_languages') # No "Category:" prefix needed
    api_result_limit = get_setting('api_result_limit', 20)

    print(f"\n--- Requesting new question ---")
    print(f"Using settings: Strategy='{page_selection_strategy}', MinWords={min_summary_words}, ContextLen={gemini_context_length}, Limit={api_result_limit}")

    page = None
    question = None
    options = None
    correct_answer = None
    wiki_page_title = None
    wiki_page_url = None

    generation_attempt = 0
    # Loop tries to fetch a VALID page AND generate a VALID question from it
    while generation_attempt < MAX_GENERATION_ATTEMPTS:
        generation_attempt += 1
        print(f"\nOverall Generation Attempt {generation_attempt}/{MAX_GENERATION_ATTEMPTS}")

        # Step 1: Get a valid Wikipedia page using the selected strategy
        # The get_wikipedia_page function handles its own retries for fetching pages
        page = get_wikipedia_page(page_selection_strategy, search_keywords, target_categories, api_result_limit)

        if not page:
            print("Failed to get a suitable page after internal retries. Aborting question generation for this request.")
            # No need to continue generation attempts if we can't even get a page
            return jsonify({"error": "Could not retrieve a suitable Wikipedia article after multiple attempts."}), 503 # Service Unavailable might fit

        wiki_page_title = page.title
        wiki_page_url = page.fullurl
        summary = page.summary # Or use page.text for potentially more content

        print(f"Attempting to generate question for: {wiki_page_title}")
        print(f"Summary length: {len(summary)} chars, ~{len(summary.split())} words.")

        # Step 2: Check if summary is long enough based on settings
        if len(summary.split()) < min_summary_words:
            print(f"Summary too short ({len(summary.split())} words, minimum {min_summary_words}). Trying to get a new page.")
            page = None # Discard this page
            # Continue the loop to try fetching a *different* page and generating from it
            continue

        # Step 3: Generate Q&A using Gemini from the valid page's summary
        question, options, correct_answer = generate_question_from_text(summary, gemini_context_length)

        if question and options and correct_answer:
            print(f"Successfully generated question for '{wiki_page_title}'.")
            break # Exit the loop, we have a valid page and question
        else:
            print(f"Failed to generate valid Q&A from summary of '{wiki_page_title}'. Trying to get a new page.")
            page = None # Discard this page, the summary might be problematic for Gemini
            # Continue the loop to try fetching a *different* page and generating from it

    # --- After the loop ---
    if not (page and question and options and correct_answer):
        print(f"Failed to generate a question after {MAX_GENERATION_ATTEMPTS} attempts (fetching page + generating Q&A).")
        # Send error response if we exhausted attempts without success
        return jsonify({"error": f"Failed to generate a trivia question after {MAX_GENERATION_ATTEMPTS} attempts."}), 500 # Internal Server Error

    # Store context for answer checking
    session['current_question'] = {
        'title': wiki_page_title,
        'url': wiki_page_url,
        'question': question,
        'options': options, # This is the dict { 'A': '...', 'B': '...' }
        'correct_answer_letter': correct_answer # Just the letter 'A', 'B', 'C', or 'D'
    }
    session.modified = True # Ensure session is saved

    print(f"Sending question to client: {question}")
    return jsonify({
        'question': question,
        'options': options, # Send the options dict
        'wiki_page_title': wiki_page_title,
        'wiki_page_url': wiki_page_url
    })


@app.route('/submit_answer', methods=['POST'])
def submit_answer():
    data = request.get_json()
    user_answer_letter = data.get('answer')
    user_confidence = data.get('confidence')

    if 'current_question' not in session:
        return jsonify({"error": "No active question found in session."}), 400

    if user_answer_letter is None or user_confidence is None:
        return jsonify({"error": "Missing answer or confidence."}), 400

    try:
        user_confidence = int(user_confidence)
        if not (0 <= user_confidence <= 100):
            raise ValueError("Confidence out of range")
    except ValueError:
        return jsonify({"error": "Invalid confidence value."}), 400

    current_q = session['current_question']
    correct_answer_letter = current_q['correct_answer_letter']

    # Get the text of the correct answer for display
    correct_answer_text = current_q['options'].get(correct_answer_letter)

    is_correct = (user_answer_letter == correct_answer_letter)

    # Calculate Brier score
    brier_score = calculate_brier_score(user_confidence, is_correct)

    # Update session statistics
    if 'stats' not in session:
        # Initialize stats if missing (shouldn't happen normally)
        session['stats'] = {'total_answered': 0, 'total_correct': 0, 'brier_scores': [], 'confidence_levels': [], 'correctness': []}
        for key in ['brier_scores', 'confidence_levels', 'correctness']: # Ensure lists exist
            if key not in session['stats']: session['stats'][key] = []

    session['stats']['total_answered'] += 1
    if is_correct:
        session['stats']['total_correct'] += 1
    session['stats']['brier_scores'].append(brier_score)
    session['stats']['confidence_levels'].append(user_confidence)
    session['stats']['correctness'].append(is_correct)

    session.modified = True # Crucial: mark session as modified

    # Store response in database
    try:
        response_entry = Response(
            session_id=session.sid if hasattr(session, 'sid') else request.remote_addr, # Use session id or IP as fallback identifier
            wiki_page_title=current_q['title'],
            question_text=current_q['question'],
            answer_options=str(current_q['options']), # Store options as string
            correct_answer=correct_answer_letter,
            user_answer=user_answer_letter,
            user_confidence=user_confidence,
            is_correct=is_correct,
            brier_score=brier_score
        )
        db.session.add(response_entry)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error saving response to database: {e}")
        # Decide if this should be a user-facing error or just logged
        # return jsonify({"error": "Failed to save response to database."}), 500

    # Clear current question from session after processing
    session.pop('current_question', None)
    session.modified = True

    return jsonify({
        "result": "correct" if is_correct else "incorrect",
        "correct_answer": correct_answer_letter,
        "correct_answer_text": correct_answer_text,
        "brier_score": round(brier_score, 3),
        "new_stats": session['stats'] # Send updated stats back
    })


# --- Main Execution ---
if __name__ == '__main__':
    # Optional: Add logic here to check/populate default AppSetting keys if they don't exist in the DB
    # This requires the app context
    with app.app_context():
        db.create_all() # Ensure tables exist

        # Example: Check and add default settings if missing
        defaults = {
            'min_summary_words': '50',
            'gemini_context_length': '3000',
            'page_selection_strategy': 'random',
            'search_keywords': 'History, Science, Technology, Art, Geography, Culture, Philosophy, Sports',
            'target_categories': 'Physics, World_War_II, Cities_in_France, Mammals, Programming_languages',
            'api_result_limit': '20'
        }
        for key, value in defaults.items():
            exists = AppSetting.query.filter_by(setting_key=key).first()
            if not exists:
                print(f"Adding default setting: {key} = {value}")
                setting = AppSetting(setting_key=key, setting_value=value)
                db.session.add(setting)
        db.session.commit() # Commit any newly added defaults

    app.run(debug=True) # IMPORTANT: Turn off debug=True in a production environment!