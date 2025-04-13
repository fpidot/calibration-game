# admin_views.py

from flask_admin.contrib.sqla import ModelView
from flask import session, flash, redirect, url_for, request
# Import WTForms components for custom form
from flask_wtf import FlaskForm
from wtforms.fields import SelectField, TextAreaField, StringField, HiddenField
from wtforms.validators import DataRequired, Optional

# Import your models
from models import AppSetting, Response



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

# --- Response View (Keep as before) ---
class ResponseAdminView(ModelView):
    """Read-only Admin view for Response model."""
    can_create = False; can_edit = False; can_delete = False
    column_list = ('timestamp','wiki_page_title','user_answer','correct_answer','is_correct','user_confidence','brier_score','session_id')
    column_filters = ('is_correct', 'wiki_page_title', 'timestamp', 'user_confidence')
    column_searchable_list = ('wiki_page_title', 'question_text', 'session_id')
    column_default_sort = ('timestamp', True)
    column_labels = { 'timestamp': 'Time', 'wiki_page_title': 'Article', 'user_answer': 'User Ans', 'correct_answer': 'Correct Ans', 'is_correct': 'Correct?', 'user_confidence': 'Confidence', 'brier_score': 'Brier Score', 'session_id': 'Session/User ID' }
    page_size = 100
    def is_accessible(self): return True
    def inaccessible_callback(self, name, **kwargs):
        flash('You are not authorized...', 'warning'); return redirect(url_for('index'))