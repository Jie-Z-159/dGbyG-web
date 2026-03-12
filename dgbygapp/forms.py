from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, RadioField, SubmitField, TextAreaField
from wtforms.fields import EmailField
from wtforms.validators import DataRequired, Length, ValidationError, Email
import re

def validate_equation(form, field):
    """验证反应方程式的格式"""
    if ' = ' not in field.data:
        raise ValidationError('Equation must contain " = " separator')
    
    # 检查两边是否都有化合物
    lhs, rhs = field.data.split(' = ', 1)
    if not lhs.strip() or not rhs.strip():
        raise ValidationError('Both sides of the equation must contain compounds')
    
    # 检查化合物格式
    for side in [lhs, rhs]:
        compounds = [c.strip() for c in side.split('+')]
        for compound in compounds:
            if not compound:
                raise ValidationError('Empty compound found')
            # 检查系数和化合物名称的格式
            if not re.match(r'^\s*(\d*[a-zA-Z0-9\[\]()=@#+-]+)\s*$', compound):
                raise ValidationError(f'Invalid compound format: {compound}')

class ReactionForm(FlaskForm):
    equation = StringField(
        'Equation',
        validators=[
            DataRequired(message="Please enter the chemical reaction formula"),
            Length(min=3, max=500, message="Equation length must be between 3 and 500 characters"),
            validate_equation
        ],
        render_kw={
            "class": "form-control"
        }
    )
    
    identifier_type = SelectField(
        'Identifier type',
        choices=[
            ('smiles', 'SMILES'),
            ('inchi', 'InChI'),
            ('inchi_key','InChI_Key'),
            ('kegg', 'KEGG'),
            ('metanetx', 'MetaNetX'),
            ('hmdb', 'HMDB'),
            ('name','Name'),
            ('bigg','Bigg (Bigg universal ID)'),
            ('chebi','ChEBI'),
            ('pubchem','PubChem'),
            ('mixed', 'Mixed Identifiers'),
        ],
        validators=[DataRequired(message="Please select an identifier type")],
        render_kw={"class": "form-control"}
    )
    
    reaction_condition = RadioField(
        'Reaction condition',
        choices=[
            ('d', 'Default'),
            ('c', 'Cytosol'),
            ('e', 'Extracellular'),
            ('n', 'Nucleus'),
            ('r', 'Endoplasmic Reticulum'),
            ('g', 'Golgi Apparatus'),
            ('l', 'Lysosome'),
            ('m', 'Mitochondria'),
            ('i', 'Inner Mitochondria'),
            ('x', 'Peroxisome'),
            ('custom', 'Custom Condition')
        ],
        validators=[DataRequired(message="Please select a reaction condition")],
        render_kw={"class": "form-check-input"}
    )
    
    submit = SubmitField('Calculate', render_kw={"class": "btn btn-primary"})

class UnifiedSearchForm(FlaskForm):
    query = StringField(
        'Search Query',
        validators=[
            DataRequired(message="Please enter a search query"),
            Length(min=1, max=200, message="Query must be between 1 and 200 characters")
        ],
        render_kw={
            "placeholder": "Enter model name, reaction ID, metabolite name, etc.",
            "class": "form-control"
        }
    )
    
    model_filter = SelectField(
        'Filter by Model (Optional)',
        choices=[('', 'All Models')],  # 动态填充
        validators=[],
        render_kw={"class": "form-control"}
    )
    
    submit = SubmitField('Search', render_kw={"class": "btn btn-primary"})


class ContactForm(FlaskForm):
    name = StringField(
        'Name',
        validators=[
            DataRequired(message="Please enter your name"),
            Length(max=120, message="Name must be 120 characters or fewer")
        ],
        render_kw={"class": "form-control", "placeholder": "Your name"}
    )

    email = EmailField(
        'Email',
        validators=[
            DataRequired(message="Please provide an email address"),
            Email(message="Please enter a valid email address"),
            Length(max=255, message="Email address must be 255 characters or fewer")
        ],
        render_kw={"class": "form-control", "placeholder": "your@email.com"}
    )

    message = TextAreaField(
        'Message',
        validators=[
            DataRequired(message="Please enter your message"),
            Length(max=2000, message="Message must be under 2000 characters")
        ],
        render_kw={"class": "form-control", "rows": 5, "placeholder": "How can we help?"}
    )

    submit = SubmitField('Send Message', render_kw={"class": "btn btn-primary"}) 