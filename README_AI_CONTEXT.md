# AI Assistant Context for Wikipedia Calibration Game

**Project Goal:** Develop a Wikipedia-based Probabilistic Trivia/Calibration Game. Users answer multiple-choice questions generated from Wikipedia articles, provide a 0-100% confidence rating, and receive scores based on correctness and calibration (Brier score). Results are stored in a PostgreSQL database and displayed via session statistics and a Chart.js calibration curve. Question generation uses the Google Gemini API. An admin interface using Flask-Admin allows managing settings and viewing responses.

**Key File Locations (in GitHub Repo Root):**
*   `app.py`: Main Flask application, routes, game logic, session management.
*   `models.py`: SQLAlchemy database model definitions (`AppSetting`, `Response`).
*   `admin_views.py`: Flask-Admin view definitions (`AppSettingAdminView`, `ResponseAdminView`).
*   `templates/index.html`: Main frontend HTML and JavaScript for the game UI.
*   `templates/admin/appsetting_edit.html`: Custom template for editing `AppSetting` in Admin.
*   `requirements.txt`: Python dependencies.
*   `migrations/`: Flask-Migrate database migration scripts.
*   `.env.example`: Example for the `.env` file (actual `.env` is local and contains secrets).

**Current Status (End of Previous Chat - April 13, 2025):**

*   **Core Game Loop:** Functional.
    *   Fetches Wikipedia articles using 'random', 'search', or 'category' strategies (configurable via Admin `AppSetting`).
    *   Generates Q&A using Gemini API (parsing of Gemini response made more robust).
    *   User can submit answers and confidence.
    *   Brier score is calculated.
    *   A gamified points score is calculated per question (based on correctness and confidence, configurable via `AppSetting`s like `score_base_correct`, `score_mult_correct`, etc.).
    *   Responses (including points and Brier score) are saved to the PostgreSQL database.
*   **Session Management & Stats:**
    *   A robust `initialize_session_stats()` function in `app.py` ensures all necessary keys are present in `session['stats']`.
    *   Frontend (`index.html`) displays:
        *   Questions Answered (Session total).
        *   Correct Answers (Session total) & Accuracy (%).
        *   "Avg Brier Score (Game)" - Resets each game.
        *   "Avg Brier Score (Session)" - Accumulates across games in the browser session.
        *   "Current Game Score" (cumulative points for the current game).
        *   "Question X / Y" (progress in the current game, Y is `game_length` from settings).
        *   "Games Played (Session)".
        *   "Average Game Score (Session)".
    *   Calibration chart (`Chart.js`) displays binned data (Avg Confidence vs. Accuracy per bin), with point size reflecting count in bin.
*   **Finite Game Loop:**
    *   `game_length` is configurable in Admin.
    *   Game ends after `game_length` questions.
    *   "Game Over!" message displayed with final game score and game Brier score.
    *   "Get New Question" button changes to "Play Again?".
    *   "Play Again?" button calls `/start_new_game` backend route, which resets per-game stats (current game score, questions this game, game Brier scores, confidence levels for chart, correctness for chart) and increments `games_played_session`, and stores `completed_game_scores_session`.
*   **Admin Interface (`Flask-Admin`):**
    *   `/admin` is functional.
    *   `AppSetting` view allows viewing and editing settings (using a custom template `appsetting_edit.html`). Editing settings (both text and the `page_selection_strategy` which *should* be a dropdown but currently renders as a text box due to complexities with the custom template) works without errors.
    *   `Response` view is read-only for submitted answers.
*   **Confidence Default:** Frontend slider defaults to 25%.
*   **Question Skipping (Partial):**
    *   "Get New Question" button is correctly disabled when a question is active and re-enabled after an answer (unless game over).

**Deferred / Incomplete Items from Recent Discussions:**

*   **Admin Dropdown for `page_selection_strategy`:** The custom template `appsetting_edit.html` renders this as a text box. While editing works, it's not the desired dropdown. This was deferred due to complexity in getting it to render correctly without breaking the edit functionality.
*   **Re-displaying Active Question on Page Refresh (Point c):** The backend (`/` route) passes `active_question_data`, but the `DOMContentLoaded` in `index.html` currently advises the user to click "Get New Question" to resync, rather than auto-rendering the question. This was simplified to avoid complex frontend/backend state synchronization on refresh for now.

**Overall Desired Functionality / Gameplan (from User's List - To Be Addressed Next):**

1.  **(DONE-ish)** **Default Confidence 25%** - Implemented.
2.  **(SKIPPED BY USER)** **Auto-Next Question** - User decided against this.
3.  **(LARGELY DONE)** **Finite Game (X Questions)** - Implemented. Minor UI polish or stat display at end of game might be desired.
4.  **User Category Selection:** Allow player to select a category for their game.
    *   From a predefined list (admin-set).
    *   OR freeform text parsed by the app (normalized, shown to user).
    *   Category-specific stats/leaderboards.
5.  **(DONE-ish)** **Quit Game Button:** A `/start_new_game` route exists which serves a similar purpose for "Play Again?". A dedicated "Quit" that just resets might be slightly different or could reuse this.
6.  **User Management & Persistence (Major Feature):**
    *   Track/manage users (session token initially).
    *   Randomly selected, jaunty nickname/handle, editable by player before game start.
    *   Nickname uniqueness.
    *   Optional email entry/confirmation for returning users (persistent accounts).
    *   Cumulative stats (across all true lifetime games for a known user) vs. individual games.
    *   Stats broken out by category played.
7.  **(V1 DONE)** **Gamified Scoring:** Points system based on confidence/correctness is implemented. Cumulative score for game is tracked.

**Planned Next Steps (From AI before chat ended):**

The immediate next steps were to focus on the remaining items from the user's list, likely starting with more advanced User Category Selection (#4) or starting the foundational work for User Management (#6) as it impacts many other "lifetime" stat features and leaderboards.

**AI's Task in Next Chat:**
Based on this context, review the current state and work with the user to implement the remaining features, prioritizing based on user preference. A good next candidate would be User Category Selection (#4) or beginning the foundational elements of User Management (#6) such as basic user identification in the session.