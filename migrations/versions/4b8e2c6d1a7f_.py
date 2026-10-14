"""Postgres also tells the engine about HPC simulations to submit or cancel

Revision ID: 4b8e2c6d1a7f
Revises: 9e1d2f3a4b5c
Create Date: 2026-10-14 23:30:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '4b8e2c6d1a7f'
down_revision = '9e1d2f3a4b5c'
branch_labels = None
depends_on = None

# the same as NOTIFY_ENGINE_FUNCTION in yaptide/persistence/models.py, at this revision
FUNCTION = """
CREATE OR REPLACE FUNCTION notify_engine() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.platform IN ('DIRECT', 'BATCH') THEN
            PERFORM pg_notify(
                'yaptide_engine',
                json_build_object('simulation', OLD.id, 'platform', OLD.platform, 'event', 'DELETED')::text
            );
        END IF;
        RETURN OLD;
    END IF;
    IF NEW.platform IN ('DIRECT', 'BATCH') AND NEW.job_state IN ('PENDING', 'CANCELED') THEN
        PERFORM pg_notify(
            'yaptide_engine',
            json_build_object('simulation', NEW.id, 'platform', NEW.platform, 'event', NEW.job_state)::text
        );
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql
"""

# the function at 9e1d2f3a4b5c, for the downgrade
PREVIOUS_FUNCTION = """
CREATE OR REPLACE FUNCTION notify_engine() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.platform = 'DIRECT' THEN
            PERFORM pg_notify('yaptide_engine', json_build_object('simulation', OLD.id, 'event', 'DELETED')::text);
        END IF;
        RETURN OLD;
    END IF;
    IF NEW.platform = 'DIRECT' AND NEW.job_state IN ('PENDING', 'CANCELED') THEN
        PERFORM pg_notify('yaptide_engine', json_build_object('simulation', NEW.id, 'event', NEW.job_state)::text);
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql
"""


def upgrade():
    """Replaces the function sending the events (Postgres only)"""
    if op.get_bind().dialect.name == "postgresql":
        op.execute(FUNCTION)


def downgrade():
    """Puts the function for direct simulations only back"""
    if op.get_bind().dialect.name == "postgresql":
        op.execute(PREVIOUS_FUNCTION)
