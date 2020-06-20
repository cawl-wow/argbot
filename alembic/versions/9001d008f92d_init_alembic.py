"""Init Alembic

Revision ID: 9001d008f92d
Revises: 
Create Date: 2020-03-19 22:43:12.793764

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '9001d008f92d'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('item_drop_bids', sa.Column('roll', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('item_drop_bids', 'roll')
