import requests
import os
import json
import math
from flask import Flask, render_template, jsonify, request, abort # Added abort (though not used currently)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, case
from dotenv import load_dotenv
import google.generativeai as genai
from datetime import datetime
from collections import defaultdict

# --- NEW: Import Flask-Admin ---
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView # View for SQLAlchemy models

# --- Initialization and Configuration ---
load_dotenv()
app = Flask(__name__)
# Set a secret key for Flask-Admin session management (needed for security features)
# In production, use a strong, randomly generated key stored securely
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default-insecure-secret-key-for-dev')

# --- Database Configuration ---
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "your_postgres_password") # !! USE YOUR ACTUAL PASSWORD !!
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "wiki_trivia_db")

# Ensure the database 'wiki_trivia_db' exists in PostgreSQL
app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Recommended practice
db = SQLAlchemy(app) # Initialize SQLAlchemy

# --- Gemini Configuration ---
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("Missing Google AI API Key. Make sure it's set in the .env file.")
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')

# --- Wikipedia Config ---
WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"


# --- Database Models ---

class UserResponse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(80), nullable=False, index=True) # Added index
    question_text = db.Column(db.Text, nullable=False)
    correct_answer = db.Column(db.String(255), nullable=False)
    submitted_answer = db.Column(db.String(255), nullable=False)
    confidence = db.Column(db.Integer, nullable=False) # Stores 0-100
    is_correct = db.Column(db.Boolean, nullable=False)
    brier_score = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    source_title = db.Column(db.String(255), nullable=True)
    def __repr__(self): return f'<Response {self.id}>'


# --- NEW: App Settings Model ---
class AppSetting(db.Model):
    key = db.Column(db.String(50), primary_key=True) # Setting name (e.g., 'min_summary_words')
    value = db.Column(db.String(255), nullable=False) # Setting value (stored as string)
    description = db.Column(db.Text, nullable=True)  # Optional description

    def __repr__(self):
        return f'<Setting {self.key}={self.value}>'


# --- Flask-Admin Setup ---

# Optional: Customize ModelView if needed
class SettingsView(ModelView):
    # Prevent creation of new settings keys via the UI (we'll pre-define them)
    can_create = False
    # Prevent deletion of settings keys
    can_delete = False
    # Columns to display in the list view
    column_list = ('key', 'value', 'description')

    # --- MODIFICATION ---
    # Explicitly define only the columns we want editable in the form view.
    # Since 'key' is the primary key and shouldn't be edited, omit it here.
    form_columns = ('value', 'description')

    # 'form_edit_rules' is now redundant if form_columns is correctly set,
    # but keeping it doesn't hurt and reinforces the read-only nature if desired.
    # Alternatively, you could remove form_edit_rules entirely if form_columns
    # is sufficient. Let's keep it for clarity for now.
    form_edit_rules = ('value', 'description')

    column_labels = {'key': 'Setting Name', 'value': 'Setting Value', 'description': 'Description'}

class UserResponseView(ModelView):
    # Make admin interface read-only for responses for safety
    can_edit = False
    can_create = False
    can_delete = False
    column_list = ('timestamp', 'session_id', 'question_text', 'is_correct', 'confidence', 'brier_score', 'source_title')
    column_default_sort = ('timestamp', True) # Sort by timestamp descending
    column_filters = ('session_id', 'is_correct', 'timestamp', 'source_title') # Add filters
    page_size = 50 # Show more items per page


# Initialize Flask-Admin
admin = Admin(app, name='WikiTrivia Admin', template_mode='bootstrap4') # Use Bootstrap 4 theme

# Add views to the admin interface
admin.add_view(SettingsView(AppSetting, db.session, name='App Settings'))
admin.add_view(UserResponseView(UserResponse, db.session, name='User Responses'))


# --- Helper Functions ---

# Helper to get a setting value with a default
def get_setting(key, default=None):
    """Gets a setting value from the DB, attempts type conversion, returns default if not found/error."""
    try:
        # Use session.get for efficient primary key lookup
        setting = db.session.get(AppSetting, key)
        if setting:
            if default is not None:
                try:
                    # Attempt conversion based on default type
                    if isinstance(default, int): return int(setting.value)
                    if isinstance(default, float): return float(setting.value)
                    if isinstance(default, bool): return setting.value.lower() in ['true', '1', 'yes', 'on']
                    # Add list/dict support via json if needed later
                    # if isinstance(default, list): return json.loads(setting.value)
                except (ValueError, TypeError, json.JSONDecodeError) as conversion_error:
                    print(f"Warning: Failed to convert setting '{key}' value '{setting.value}' to type {type(default).__name__}. Error: {conversion_error}. Using default.")
                    return default
            return setting.value # Return as string if no default or type hint
        return default # Setting key not found
    except Exception as e:
        print(f"Error retrieving setting '{key}': {e}. Using default.")
        return default

# Function to create default settings if they don't exist
def create_default_settings():
    """Checks for essential settings and creates them with defaults if missing."""
    with app.app_context(): # Ensure we have app context for DB operations
        defaults = {
            'min_summary_words': {'value': '25', 'description': 'Minimum words required in Wikipedia summary to generate a question.'},
            'gemini_context_length': {'value': '2000', 'description': 'Max characters of summary sent to Gemini.'}
            # Add other future settings here
        }
        needs_commit = False
        for key, data in defaults.items():
            setting = db.session.get(AppSetting, key)
            if not setting:
                print(f"Creating default setting: {key}={data['value']}")
                new_setting = AppSetting(key=key, value=data['value'], description=data['description'])
                db.session.add(new_setting)
                needs_commit = True
        if needs_commit:
            try:
                db.session.commit() # Commit any new settings
            except Exception as e:
                print(f"Error committing default settings: {e}")
                db.session.rollback()

# Gemini Prompt Creator
def create_gemini_prompt(title, summary):
    # Use setting for context length
    max_summary_length = get_setting('gemini_context_length', 2000)
    truncated_summary = summary[:max_summary_length]
    if len(summary) > max_summary_length: truncated_summary += "..."
    prompt = f"""
Context:
Title: {title}
Summary: {truncated_summary}

Task: Based *only* on the provided Context, generate a single multiple-choice trivia question. The question should test a factual detail clearly present in the Summary.

Output Format Requirements:
Provide your response *only* as a valid JSON object with the following exact keys:
- "question": A string containing the question text (e.g., "What year was the subject born?").
- "correct_answer": A string containing the correct answer based *only* on the text.
- "distractors": A JSON array of 3 strings, each being a plausible but incorrect answer related to the question. Do not repeat the correct answer in the distractors. Ensure distractors are relevant but demonstrably wrong according to the text or general knowledge related to the text.

Example Context:
Title: Eiffel Tower
Summary: The Eiffel Tower is a wrought-iron lattice tower on the Champ de Mars in Paris, France. It is named after the engineer Gustave Eiffel, whose company designed and built the tower. Constructed from 1887 to 1889 as the centerpiece of the 1889 World's Fair...

Example Output:
{{
  "question": "Who was the engineer the Eiffel Tower is named after?",
  "correct_answer": "Gustave Eiffel",
  "distractors": ["Napoleon Bonaparte", "Charles de Gaulle", "Leonardo da Vinci"]
}}

Constraints:
- Base the question and *especially* the correct answer strictly on the provided Summary text.
- Do not ask questions where the answer is not in the Summary.
- Generate exactly one question.
- Ensure distractors are plausible but verifiably incorrect based on the Summary or closely related common knowledge.
- Output *only* the JSON object, with no other surrounding text or explanations.

Now, generate the question based on the Context provided above.
"""
    return prompt

# Brier Score Calculator
def calculate_brier_score(confidence_percent, is_correct):
    probability = confidence_percent / 100.0
    outcome = 1.0 if is_correct else 0.0
    return (probability - outcome) ** 2


# --- Flask Routes ---
@app.route('/')
def index():
    """Renders the main HTML page and ensures DB tables & default settings exist."""
    # No need for explicit app_context here as Flask handles it in routes
    # db.create_all() might be better placed in init script or using Flask-Migrate
    # But for simplicity, keep it here for now. It's idempotent.
    db.create_all()
    create_default_settings() # Ensure default settings exist
    return render_template('index.html')


@app.route('/get_trivia_question')
def get_trivia_question():
    """Fetches a random Wikipedia article and generates a trivia question."""
    # Use setting for minimum summary words
    min_words = get_setting('min_summary_words', 15)

    wiki_params = {
        "action": "query", "format": "json", "generator": "random",
        "grnnamespace": 0, "grnlimit": 1, "prop": "extracts",
        "exintro": True, "explaintext": True, "origin": "*"
    }
    try: # Wikipedia Fetch
        wiki_response = requests.get(WIKIPEDIA_API_URL, params=wiki_params, timeout=10)
        wiki_response.raise_for_status()
        wiki_data = wiki_response.json()
        pages = wiki_data.get('query', {}).get('pages', {})
        if not pages: raise ValueError("No pages found in Wikipedia API response")
        page_id = list(pages.keys())[0]
        page_data = pages[page_id]
        title = page_data.get('title', 'Unknown Title')
        summary = page_data.get('extract', '')

        # Use setting in check
        if not summary or len(summary.split()) < min_words:
            print(f"Summary for '{title}' too short (< {min_words} words), skipping.")
            # Consider adding retry logic here if this happens often
            return jsonify({"error": f"Summary for '{title}' too short/missing (min {min_words} words)."}), 400

    except requests.exceptions.RequestException as e:
        print(f"Error fetching from Wikipedia API: {e}")
        return jsonify({"error": "Could not connect to Wikipedia API"}), 503
    except (ValueError, KeyError, IndexError) as e:
        print(f"Error parsing Wikipedia API response: {e}")
        return jsonify({"error": "Could not parse Wikipedia API response"}), 500

    try: # Gemini Call
        prompt = create_gemini_prompt(title, summary)
        gemini_response = gemini_model.generate_content(prompt)
        response_text = ""
        if gemini_response.parts:
            response_text = gemini_response.parts[0].text
        else:
            reason="Unknown"; print(f"Gemini response blocked/empty. Feedback: {gemini_response.prompt_feedback}")
            if hasattr(gemini_response.prompt_feedback, 'block_reason'): reason = str(gemini_response.prompt_feedback.block_reason)
            return jsonify({"error": f"Gemini response blocked or empty. Reason: {reason}"}), 500

        json_start = response_text.find('{')
        json_end = response_text.rfind('}') + 1
        if json_start != -1 and json_end != -1:
            clean_response_text = response_text[json_start:json_end]
        else:
            raise ValueError(f"Could not find valid JSON object in Gemini response. Raw: {response_text}")

        question_data = json.loads(clean_response_text)
        if not all(k in question_data for k in ["question", "correct_answer", "distractors"]):
            raise ValueError("Gemini response missing required keys.")
        if not isinstance(question_data["distractors"], list) or len(question_data["distractors"]) != 3:
             raise ValueError("Gemini response 'distractors' is not a list of 3 strings.")

        question_data['source_title'] = title
        return jsonify(question_data)

    except genai.types.generation_types.BlockedPromptException as e:
         print(f"Gemini Prompt blocked: {e}")
         return jsonify({"error": f"Content generation blocked by API safety filters. {e}"}), 400
    except Exception as e: # Catches JSON parsing errors too
        print(f"Error interacting with Gemini API or parsing response: {e}")
        return jsonify({"error": "Failed to generate question via AI model or parse its response"}), 500


@app.route('/submit_answer', methods=['POST'])
def submit_answer():
    """Receives answer submission, calculates score, saves to DB."""
    data = request.get_json()
    required_keys = ['question', 'correct_answer', 'submitted_answer', 'confidence', 'session_id', 'source_title']
    if not data or not all(key in data for key in required_keys):
        return jsonify({"error": "Missing data in submission"}), 400

    try:
        question_text = data['question']
        correct_answer = data['correct_answer']
        submitted_answer = data['submitted_answer']
        confidence = int(data['confidence'])
        session_id = data['session_id']
        source_title = data['source_title']

        # Validation check for confidence (0-100)
        if not (0 <= confidence <= 100):
            raise ValueError("Confidence must be between 0 and 100.")

        is_correct = (submitted_answer == correct_answer)
        brier_score = calculate_brier_score(confidence, is_correct)

        response_record = UserResponse(
            session_id=session_id, question_text=question_text, correct_answer=correct_answer,
            submitted_answer=submitted_answer, confidence=confidence, is_correct=is_correct,
            brier_score=brier_score, source_title=source_title
        )
        db.session.add(response_record)
        db.session.commit()

        return jsonify({
            "message": "Answer submitted successfully", "is_correct": is_correct,
            "correct_answer": correct_answer, "brier_score": brier_score,
            "response_id": response_record.id
        }), 200

    except ValueError as e:
         print(f"Validation Error: {e}")
         return jsonify({"error": f"Invalid data: {e}"}), 400
    except Exception as e:
        db.session.rollback() # Rollback DB changes on error
        print(f"Error submitting answer: {e}")
        return jsonify({"error": "Failed to process answer submission"}), 500


@app.route('/get_stats')
def get_stats():
    """Calculates and returns aggregate stats for a given session."""
    session_id = request.args.get('session_id')
    if not session_id:
        return jsonify({"error": "Missing session_id parameter"}), 400

    try:
        # Query using SQLAlchemy's func for aggregation
        stats = db.session.query(
            func.count(UserResponse.id).label('total_questions'),
            func.sum(case((UserResponse.is_correct == True, 1), else_=0)).label('correct_answers'),
            func.avg(UserResponse.brier_score).label('average_brier_score')
        ).filter(UserResponse.session_id == session_id).one() # Use .one() as we expect one row of stats

        total_questions = stats.total_questions or 0 # Handle case where no questions are answered yet
        correct_answers = stats.correct_answers or 0
        average_brier_score = stats.average_brier_score if stats.average_brier_score is not None else 0.0 # Handle None if no questions

        percent_correct = (correct_answers / total_questions * 100) if total_questions > 0 else 0

        return jsonify({
            "session_id": session_id,
            "total_questions": total_questions,
            "correct_answers": correct_answers,
            "percent_correct": round(percent_correct, 1),
            "average_brier_score": round(average_brier_score, 3) # Brier score is typically shown with more decimals
        })

    except Exception as e:
        print(f"Error calculating stats for session {session_id}: {e}")
        return jsonify({"error": "Failed to calculate statistics"}), 500


@app.route('/get_calibration_data')
def get_calibration_data():
    """Fetches confidence and correctness data for the session."""
    session_id = request.args.get('session_id')
    if not session_id:
        return jsonify({"error": "Missing session_id parameter"}), 400

    try:
        # Query for individual confidence and correctness pairs
        calibration_data = db.session.query(
            UserResponse.confidence,
            UserResponse.is_correct
        ).filter(UserResponse.session_id == session_id).order_by(UserResponse.timestamp).all()

        # Format data for easy JSON serialization
        results = [
            {"confidence": row.confidence, "is_correct": row.is_correct}
            for row in calibration_data
        ]

        return jsonify(results)

    except Exception as e:
        print(f"Error fetching calibration data for session {session_id}: {e}")
        return jsonify({"error": "Failed to fetch calibration data"}), 500


# --- Main Execution ---
if __name__ == '__main__':
    # debug=True enables auto-reloading and error pages during development
    # In production, set debug=False and use a proper WSGI server (like Gunicorn or Waitress)
    app.run(debug=True)