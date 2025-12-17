"""merge creem_payments and character_ids

Revision ID: 5919d061f98c
Revises: creem_payments_001, i2j3k4l5m6n7
Create Date: 2025-12-16 15:47:38.309820

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5919d061f98c'
down_revision = ('creem_payments_001', 'i2j3k4l5m6n7')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
