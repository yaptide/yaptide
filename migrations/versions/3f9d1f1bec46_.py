"""empty message

Revision ID: 3f9d1f1bec46
Revises: 06c32cf470e7
Create Date: 2024-10-25 16:20:27.118215

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3f9d1f1bec46'
down_revision = '06c32cf470e7'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('Estimator', schema=None) as batch_op:
        batch_op.drop_constraint('Estimator_simulation_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('Estimator_simulation_id_fkey', 'Simulation', ['simulation_id'], ['id'], ondelete='CASCADE')

    with op.batch_alter_table('Input', schema=None) as batch_op:
        batch_op.drop_constraint('Input_simulation_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('Input_simulation_id_fkey', 'Simulation', ['simulation_id'], ['id'], ondelete='CASCADE')

    with op.batch_alter_table('Logfiles', schema=None) as batch_op:
        batch_op.drop_constraint('Logfiles_simulation_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('Logfiles_simulation_id_fkey', 'Simulation', ['simulation_id'], ['id'], ondelete='CASCADE')

    with op.batch_alter_table('Page', schema=None) as batch_op:
        batch_op.drop_constraint('Page_estimator_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('Page_estimator_id_fkey', 'Estimator', ['estimator_id'], ['id'], ondelete='CASCADE')

    with op.batch_alter_table('Task', schema=None) as batch_op:
        batch_op.drop_constraint('Task_simulation_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('Task_simulation_id_fkey', 'Simulation', ['simulation_id'], ['id'], ondelete='CASCADE')

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('Task', schema=None) as batch_op:
        batch_op.drop_constraint('Task_simulation_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('Task_simulation_id_fkey', 'Simulation', ['simulation_id'], ['id'])

    with op.batch_alter_table('Page', schema=None) as batch_op:
        batch_op.drop_constraint('Page_estimator_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('Page_estimator_id_fkey', 'Estimator', ['estimator_id'], ['id'])

    with op.batch_alter_table('Logfiles', schema=None) as batch_op:
        batch_op.drop_constraint('Logfiles_simulation_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('Logfiles_simulation_id_fkey', 'Simulation', ['simulation_id'], ['id'])

    with op.batch_alter_table('Input', schema=None) as batch_op:
        batch_op.drop_constraint('Input_simulation_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('Input_simulation_id_fkey', 'Simulation', ['simulation_id'], ['id'])

    with op.batch_alter_table('Estimator', schema=None) as batch_op:
        batch_op.drop_constraint('Estimator_simulation_id_fkey', type_='foreignkey')
        batch_op.create_foreign_key('Estimator_simulation_id_fkey', 'Simulation', ['simulation_id'], ['id'])

    # ### end Alembic commands ###
