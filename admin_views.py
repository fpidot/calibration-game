# admin_views.py

from flask_admin.contrib.sqla import ModelView
from flask import session, flash, redirect, url_for, request # Import necessary Flask components if needed for security later
# from flask_login import current_user # Example if you add Flask-Login

# Import your models to link views to them
from models import AppSetting, Response

class AppSettingAdminView(ModelView):
    """Customized Admin view for AppSetting model."""
    # Columns displayed in the list view
    column_list = ('setting_key', 'setting_value', 'description')
    # Columns that can be searched
    column_searchable_list = ('setting_key', 'setting_value', 'description')
    # Columns that can be edited directly in the list view
    # column_editable_list = ['setting_value'] # Use cautiously
    # Columns that can be filtered
    column_filters = ('setting_key',)
    # Form configuration
    form_columns = ('setting_value',)
    # Prettify column headers
    form_args = {
        'setting_key': {
            'render_kw': {'readonly': True}
        },
         'description': {
            'render_kw': {'readonly': True}
         }
    }
    column_labels = {
        'setting_key': 'Setting Key',
        'setting_value': 'Value',
        'description': 'Description'
    }
    page_size = 50 # Show more items per page if desired

    # --- Security (Placeholder - implement proper auth later) ---
    def is_accessible(self):
        # ToDo: Replace with actual authentication check
        # return current_user.is_authenticated and current_user.is_admin
        return True # Allow access for now

    def inaccessible_callback(self, name, **kwargs):
        flash('You are not authorized to access this page.', 'warning')
        # ToDo: Redirect to a login page
        # return redirect(url_for('login', next=request.url))
        return redirect(url_for('index')) # Redirect to main page for now

class ResponseAdminView(ModelView):
    """Read-only Admin view for Response model."""
    # Make this view read-only
    can_create = False
    can_edit = False
    can_delete = False

    # Columns to display in the list view
    column_list = (
        'timestamp',
        'wiki_page_title',
        'user_answer',
        'correct_answer',
        'is_correct',
        'user_confidence',
        'brier_score',
        'session_id' # Include session ID for context
    )
    # Columns to allow filtering on
    column_filters = ('is_correct', 'wiki_page_title', 'timestamp', 'user_confidence')
    # Columns to allow searching
    column_searchable_list = ('wiki_page_title', 'question_text', 'session_id')
    # Default sort order (e.g., newest first)
    column_default_sort = ('timestamp', True)
    # Labels for clarity
    column_labels = {
        'timestamp': 'Time',
        'wiki_page_title': 'Article',
        'user_answer': 'User Ans',
        'correct_answer': 'Correct Ans',
        'is_correct': 'Correct?',
        'user_confidence': 'Confidence',
        'brier_score': 'Brier Score',
        'session_id': 'Session/User ID'
    }
    page_size = 100 # Show more responses per page

    # --- Security (Placeholder) ---
    def is_accessible(self):
        # ToDo: Replace with actual authentication check
        return True

    def inaccessible_callback(self, name, **kwargs):
        flash('You are not authorized to access this page.', 'warning')
        # ToDo: Redirect to a login page
        return redirect(url_for('index'))