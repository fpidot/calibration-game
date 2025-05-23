# Wikipedia Calibration Game: Project Plan

**Project Goal:** Develop a Wikipedia-based Probabilistic Trivia/Calibration Game. Users answer multiple-choice questions generated from Wikipedia articles, provide a 0-100% confidence rating, and receive scores based on correctness and calibration (Brier score). Results are stored in a PostgreSQL database and displayed via session statistics and a Chart.js calibration curve. Question generation uses the Google Gemini API. An admin interface using Flask-Admin allows managing settings and viewing responses. Users will have persistent accounts to track their progress and compete on leaderboards.

**Key Technologies:**
*   **Backend:** Flask (Python)
*   **Database:** PostgreSQL (with SQLAlchemy ORM and Flask-Migrate)
*   **Frontend:** HTML, CSS, JavaScript, Chart.js
*   **Admin:** Flask-Admin
*   **AI for Q&A:** Google Gemini API
*   **Environment:** Python virtual environment, `.env` for secrets

**Key File Locations (in GitHub Repo Root):**
*   `app.py`: Main Flask application, routes, game logic, session management.
*   `models.py`: SQLAlchemy database model definitions (`User`, `AppSetting`, `Response`).
*   `admin_views.py`: Flask-Admin view definitions.
*   `templates/index.html`: Main frontend HTML and JavaScript for the game UI.
*   `templates/admin/appsetting_edit.html`: Custom template for editing `AppSetting` in Admin.
*   `templates/login.html`, `templates/register.html`, `templates/profile.html`, `templates/leaderboard.html` (To be created)
*   `requirements.txt`: Python dependencies.
*   `migrations/`: Flask-Migrate database migration scripts.
*   `.env.example`: Example for the `.env` file.

---

## Current Implemented Features (as of May 23, 2025)

**I. Core Game Loop:**
*   Dynamic question generation from Wikipedia articles using the Gemini API.
*   Multiple-choice question presentation.
*   User input for answer and 0-100% confidence.
*   Scoring:
    *   Brier score calculated per question.
    *   Gamified points system based on correctness and confidence (configurable via Admin).
*   Database storage (`Response` model) for each answer, including question details, user answer, confidence, correctness, Brier score, points, and game category.
*   Finite game length (configurable via `AppSetting` `game_length`).
    *   "Game Over" display with final game score and average Brier score for the game.
    *   "Play Again?" functionality resets game-specific stats.

**II. Session Management & UI:**
*   Session-based tracking of game statistics (`total_answered`, `total_correct`, `brier_scores`, `game_brier_scores`, `confidence_levels`, `correctness`, `cumulative_score` for current game, `questions_this_game`, `games_played_session`, `completed_game_scores_session`).
*   Frontend display of current session and current game statistics.
*   Calibration chart (Chart.js) displaying binned confidence vs. accuracy for the current game.
*   Button text changes dynamically ("Begin Game", "Get Next Question", "Play Again?").
*   Active question re-displayed on page refresh (preventing easy skipping).

**III. User Category Selection:**
*   Users can select a game category from a predefined list (admin-set via `AppSetting` `user_selectable_categories`) or enter a freeform topic.
*   Freeform topics are standardized by the Gemini API into a thematic category name.
*   The chosen/processed category guides Wikipedia page selection for question generation.
*   The active `game_category` is displayed to the user during the question and stored with each `Response`.

**IV. Basic User Identification (Nickname Choice):**
*   New users are presented with a suggested "jaunty" nickname.
*   Users can accept the suggestion or enter their own custom nickname before their first game.
*   Nickname uniqueness is checked against the database.
*   A `User` record (with `id` and `nickname`) is created upon nickname confirmation.
*   All subsequent game actions (`Response` records) are linked to this `user_id`.
*   The user's nickname is displayed in the UI.
*   Game actions are blocked until a nickname is set.

**V. Administration (`Flask-Admin`):**
*   Functional `/admin` interface.
*   `AppSetting` view: Allows viewing and editing of all application settings.
    *   Custom edit template (`appsetting_edit.html`) used.
    *   `page_selection_strategy` setting rendered as a dropdown.
*   `Response` view: Read-only view of all submitted responses, showing user nickname and game category.
*   `User` view: Read-only view of created users and their nicknames.

---

## Planned Future Development Roadmap

**Phase 1: User Account Persistence & Management (Current Focus)**
*   **Sub-Phase 1.1: Registration (Email/Password)**
    *   **Task:** Allow users to "claim" their existing nickname/progress by associating it with an email and password.
    *   **Details:**
        *   Enhance `User` model: `email` (unique, indexed), `password_hash`, `email_confirmed_at` (nullable), `created_at`, `last_login_at`.
        *   Create `/register` route and `register.html` template.
        *   Implement Flask-WTF form for email, password, password confirmation. Nickname can be pre-filled if registering an existing session's user.
        *   Implement password hashing (e.g., `werkzeug.security`).
        *   Update existing `User` record or create new if truly new registration.
        *   Log user in upon successful registration (update session).
*   **Sub-Phase 1.2: Login/Logout**
    *   **Task:** Enable returning users to log in.
    *   **Details:**
        *   Create `/login` route and `login.html` template with Flask-WTF form.
        *   Implement login logic (verify email/password_hash).
        *   Update session on login (`user_id`, `nickname`, clear setup flags).
        *   Create `/logout` route to clear user-specific session data.
        *   Update UI with Login/Logout/Register links.
*   **Sub-Phase 1.3: "Forgot Password" (Stretch Goal for this phase)**
    *   Generate password reset tokens, email them, allow password update.

**Phase 2: Enhanced User Profile & Statistics**
*   **Task:** Create a user profile page displaying detailed statistics.
*   **Details:**
    *   `/profile` route (requires login).
    *   Display lifetime aggregate stats (total games, total Qs, overall accuracy, overall avg. Brier, avg. game score per game).
    *   Display category-specific lifetime stats (accuracy, Brier, games played, avg score per category).
    *   Potentially list recent game history with scores.
    *   `profile.html` template.

**Phase 3: Leaderboards**
*   **Task:** Implement public leaderboards.
*   **Details:**
    *   `/leaderboard` route.
    *   Define ranking metrics (e.g., avg game score over min X games, highest total score, best calibration over min X questions).
    *   Implement DB queries for ranking.
    *   Filters: Overall, Per Category, Time-based (All-time, Monthly).
    *   `leaderboard.html` template.

**Phase 4: UI/UX Polish & Refinements**
*   **Task:** Improve overall user experience.
*   **Details:**
    *   AJAX-ify nickname setting for smoother UX (no full reload if possible).
    *   More granular error handling and feedback.
    *   Visual improvements, mobile responsiveness.
    *   Review and refine gamification aspects.

**Phase 5: Advanced Features & Maintenance**
*   **Task:** Consider further enhancements.
*   **Details:**
    *   Email confirmation for new registrations.
    *   User avatars.
    *   "Challenge a friend" or social sharing (very advanced).
    *   Regular maintenance, dependency updates, bug fixes.

---

## Deferred / Technical Debt / Minor Issues to Revisit

*   **Admin Dropdown for `page_selection_strategy`:** While the custom template aims for a dropdown, confirm it robustly handles all edit/display scenarios without degrading to a text box. (README_AI_CONTEXT mentioned it was fixed, confirm this).
*   **Robustness of Gemini Q&A Parsing:** Continuously monitor and improve if new unparseable formats emerge.
*   **Scalability of Leaderboard Queries:** If user base grows, leaderboard queries might need optimization (caching, denormalization).
*   **Error Handling in `get_wikipedia_page`:** Make failure modes more graceful (e.g., if a chosen category consistently yields no usable pages).