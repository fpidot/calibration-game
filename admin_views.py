# admin_views.py

from flask_admin.contrib.sqla import ModelView
from flask import session # You might need session or current_user later for security
# from flask_login import current_user # Example if you add Flask-Login

# Import your models if needed for customization (e.g., formatting)
# from .models import AppSetting

class AppSettingAdminView(ModelView):
    """Customized Admin view for AppSetting model."""

    # --- Basic Customization ---
    # Columns displayed in the list view
    column_list = ('setting_key', 'setting_value', 'description')

    # Columns that can be searched
    column_searchable_list = ('setting_key', 'setting_value', 'description')

    # Columns that can be edited directly in the list view (use with caution)
    # column_editable_list = ['setting_value']

    # Columns that can be filtered
    column_filters = ('setting_key',)

    # How the form looks for creating/editing
    # You can customize fields further here if needed
    form_columns = ('setting_key', 'setting_value', 'description')

    # --- Security (Optional but Recommended) ---
    # You might want to restrict access to the admin panel later.
    # Here's a basic example (assumes you implement some login system)
    # def is_accessible(self):
    #     # Example: Check if user is logged in and is an admin
    #     # return current_user.is_authenticated and current_user.is_admin
    #     # For now, allow access:
    #     return True

    # def inaccessible_callback(self, name, **kwargs):
    #     # Redirect to login page if user doesn't have access
    #     # return redirect(url_for('login', next=request.url))
    #     # For now, just return a simple message:
    #     return "You are not authorized to access this page."

    # --- Add other model views here if needed ---
    # Example:
    # class ResponseAdminView(ModelView):
    #     can_create = False
    #     can_edit = False
    #     can_delete = False
    #     column_list = ('timestamp', 'wiki_page_title', 'user_answer', 'user_confidence', 'is_correct', 'brier_score', 'session_id')
    #     column_filters = ('is_correct', 'wiki_page_title', 'timestamp')
    #     column_searchable_list = ('wiki_page_title', 'question_text', 'session_id')