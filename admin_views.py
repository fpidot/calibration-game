# admin_views.py

from flask_admin.contrib.sqla import ModelView
from flask_admin.model.fields import InlineFieldList
from flask import session, flash, redirect, url_for, request
# Import WTForms components for custom form
from flask_wtf import FlaskForm
from wtforms.fields import SelectField, TextAreaField, StringField, HiddenField
from wtforms.validators import DataRequired, Optional

# Import your models
from models import AppSetting, Response, User, UserFeedback



# --- Custom WTForm for Editing AppSetting ---
# This form will be used *only* for data validation and structure.
# Rendering will be handled manually in the template.
class AppSettingEditForm(FlaskForm):
    # Hidden field for ID is essential for Flask-Admin context
    id = HiddenField()
    # Field for the specific value being edited. We only need ONE value field here.
    # The template will decide whether to render a select or text area.
    # The view logic will populate the correct data on GET and read it on POST.
    setting_value = StringField('Value', validators=[Optional()]) # Use StringField as a base

    # We don't strictly need key/description here as we'll display them manually,
    # but including them might help if Flask-Admin relies on their presence.
    setting_key = StringField('Setting Key')
    description = StringField('Description')

    # Note: No dynamic __init__ needed here. View logic will handle population.

# --- Flask-Admin ModelView ---
class AppSettingAdminView(ModelView):
    """Customized Admin view for AppSetting model using custom forms and template."""

# Define the choices for the strategy dropdown
    STRATEGY_CHOICES = [
    ('', '-- Select Strategy --'),
    ('random', 'Random Page'),
    ('search', 'Keyword Search'),
    ('category', 'Category Members')
]
    # --- Basic View Configuration ---
    column_list = ('setting_key', 'setting_value', 'description')
    column_searchable_list = ('setting_key', 'setting_value', 'description')
    column_filters = ('setting_key',)
    column_labels = {'setting_key': 'Setting Key','setting_value': 'Value','description': 'Description'}
    page_size = 50

    # --- Form Configuration ---
    # Use our custom WTForm class
    form = AppSettingEditForm
    # Specify a custom template for the edit view
    edit_template = 'admin/appsetting_edit.html' # We need to create this template file

    # Disable Flask-Admin's automatic form rules/args as we use a custom template
    form_edit_rules = None
    form_args = None
    form_widget_args = None
    form_extra_fields = None

    def get_edit_context(self, **kwargs):
        """Pass extra context to the edit template."""
        context = super(AppSettingAdminView, self).get_edit_context(**kwargs)
        # Add our choices list to the context
        context['strategy_choices'] = self.STRATEGY_CHOICES
        return context
    
    # Override update_model to read ONLY setting_value from the form
    def update_model(self, form, model):
        try:
            # Read data from the single 'setting_value' field defined in the form
            new_value = form.setting_value.data
            model.setting_value = new_value
            self.session.add(model)
            self.session.commit()
            flash(f"Setting '{model.setting_key}' updated successfully.", 'success')
            return True
        except Exception as ex:
            # ... (error handling as before) ...
            if not self.handle_view_exception(ex):
                flash(f'Failed to update setting. {ex}', 'error')
            self.session.rollback()
            return False

    # Pass extra data to the custom template if needed
    def get_edit_data(self, id):
         return self.session.query(self.model).get(id)

    # --- Security (Placeholder) ---
    def is_accessible(self): return True
    def inaccessible_callback(self, name, **kwargs):
        flash('You are not authorized...', 'warning'); return redirect(url_for('index'))

def user_nickname_formatter(view, context, model, name):
    """
    Formatter function to display user nickname in Response list view.
    `view` is the current administrative view.
    `context` is an Jinja2 context.
    `model` is the model object.
    `name` is the name of the property to retrieve.
    """
    if model.user:  # 'user' is the relationship attribute in Response model
        return model.user.nickname
    return "N/A (No User)"


class ResponseAdminView(ModelView):
    can_create = False
    can_edit = False
    can_delete = False
    
    column_list = (
        'timestamp', 'user', 'wiki_page_title', 'user_answer', 
        'correct_answer', 'is_correct', 'user_confidence', 
        'brier_score', 'game_category'
    )
    
    # Use the new function formatter
    column_formatters = {
        'user': user_nickname_formatter  # Assign the function directly
    }
    
    column_filters = ('is_correct', 'wiki_page_title', 'timestamp', 'user_confidence', 'game_category', 'user.nickname')
    column_searchable_list = ('wiki_page_title', 'question_text', 'user.nickname', 'game_category')
    column_default_sort = ('timestamp', True)
    
    column_labels = { 
        'timestamp': 'Time', 
        'user': 'User Nickname', # This 'user' key matches the field in column_list
        'wiki_page_title': 'Article', 
        'user_answer': 'User Ans', 
        'correct_answer': 'Correct Ans', 
        'is_correct': 'Correct?', 
        'user_confidence': 'Confidence', 
        'brier_score': 'Brier Score', 
        'game_category': 'Game Category'
    }
    page_size = 100

    def is_accessible(self): return True # Add your access control
    def inaccessible_callback(self, name, **kwargs):
        flash('You are not authorized...', 'warning'); return redirect(url_for('index'))


class UserAdminView(ModelView):
    column_list = ('id', 'nickname', 'created_at')
    column_searchable_list = ('nickname',)
    column_filters = ('created_at',)
    can_edit = False 
    can_create = False 
    page_size = 100

    def is_accessible(self): return True # Add your access control
    def inaccessible_callback(self, name, **kwargs):
        flash('You are not authorized...', 'warning'); return redirect(url_for('index'))
    
class UserFeedbackAdminView(ModelView):
    # Which columns to display in the list view
    column_list = ('submitted_at', 'user', 'nickname_at_submission', 'email_address_at_submission', 
                   'feedback_type', 'message', 'is_resolved', 'page_context')
    
    # Which columns can be searched
    column_searchable_list = ('nickname_at_submission', 'email_address_at_submission', 'message', 
                              'feedback_type', 'page_context', 'user.nickname', 'user.email')
    
    # Which columns can be filtered
    column_filters = ('feedback_type', 'submitted_at', 'is_resolved', 'user.nickname')
    
    # Default sort
    column_default_sort = ('submitted_at', True) # True for descending (newest first)

    # Make message display a bit better in list (optional, can be slow with lots of text)
    # column_formatters = {
    #    'message': lambda v, c, m, p: (m.message[:100] + '...') if m.message and len(m.message) > 100 else m.message
    # }

    # Control which fields are editable in the form view
    # For now, let's allow editing of resolution status and admin notes
    form_columns = ('user', 'nickname_at_submission', 'email_address_at_submission', 
                    'feedback_type', 'message', 'page_context', 'user_agent_string',
                    'is_resolved', 'admin_notes') # 'submitted_at' is auto

    # Make some fields read-only in the edit form if they shouldn't be changed by admin
    form_edit_rules = (
        'user', 'nickname_at_submission', 'email_address_at_submission', 
        'feedback_type', 'message', 'page_context', 'user_agent_string',
        'submitted_at', # Should be read-only
        'is_resolved', 
        'admin_notes'
    )
    # Or, more simply, define which fields CANNOT be edited:
    # form_excluded_columns_on_edit = ['submitted_at', 'user_id', 'user_agent_string', 'page_context']
    # form_widget_args to make some fields readonly
    form_widget_args = {
        'submitted_at': {'readonly': True},
        'user': {'readonly': True}, # Don't change the linked user
        'nickname_at_submission': {'readonly': True},
        'email_address_at_submission': {'readonly': True},
        'feedback_type': {'readonly': True}, # Usually don't change this after submission
        'message': {'readonly': True},       # Don't change the user's message
        'user_agent_string': {'readonly': True},
        'page_context': {'readonly': True},
    }


    # Can admin create new feedback entries? Probably not.
    can_create = False
    # Can admin delete feedback? Your choice.
    can_delete = True # Or False
    # Can admin edit? Yes, for is_resolved and admin_notes.
    can_edit = True

    page_size = 50 # Number of items per page

    def is_accessible(self):
        # Add your access control logic here, e.g., check if current_user is admin
        # For now, let's assume basic access or you'll add your real check
        return True # Replace with your actual admin check

    def inaccessible_callback(self, name, **kwargs):
        flash('You are not authorized to access this page.', 'warning')
        return redirect(url_for('index')) # Or your login page