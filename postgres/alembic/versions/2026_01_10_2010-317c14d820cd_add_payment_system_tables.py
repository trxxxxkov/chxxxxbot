"""Add payment system tables.

Revision ID: 317c14d820cd
Revises: 006
Create Date: 2026-01-10 20:10:21.772098+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '317c14d820cd'
down_revision: Union[str, None] = '006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply migration: Add payment system tables and balance column."""
    # 1. Add balance column to users table
    op.add_column(
        'users',
        sa.Column('balance',
                  sa.Numeric(precision=10, scale=4),
                  server_default='0.1000',
                  nullable=False,
                  comment='User balance in USD'))
    op.create_index('idx_users_balance', 'users', ['balance'])

    # 2. Create PaymentStatus enum
    payment_status_enum = postgresql.ENUM('completed',
                                          'refunded',
                                          name='paymentstatus',
                                          create_type=False)
    payment_status_enum.create(op.get_bind(), checkfirst=True)

    # 3. Create payments table
    op.create_table(
        'payments',
        sa.Column('id',
                  sa.Integer(),
                  autoincrement=True,
                  nullable=False,
                  comment='Payment ID'),
        sa.Column('user_id',
                  sa.BigInteger(),
                  nullable=False,
                  comment='User who made the payment'),
        sa.Column(
            'telegram_payment_charge_id',
            sa.String(255),
            nullable=False,
            comment=
            'Telegram payment charge ID from SuccessfulPayment (for refunds)'),
        sa.Column('stars_amount',
                  sa.Integer(),
                  nullable=False,
                  comment='Amount paid in Telegram Stars'),
        sa.Column(
            'nominal_usd_amount',
            sa.Numeric(precision=10, scale=4),
            nullable=False,
            comment='Nominal USD value (stars * rate) WITHOUT commissions'),
        sa.Column(
            'credited_usd_amount',
            sa.Numeric(precision=10, scale=4),
            nullable=False,
            comment='USD amount credited to user balance (AFTER commissions)'),
        sa.Column('commission_k1',
                  sa.Numeric(precision=5, scale=4),
                  nullable=False,
                  comment='Telegram withdrawal fee rate (k1, typically 0.35)'),
        sa.Column(
            'commission_k2',
            sa.Numeric(precision=5, scale=4),
            nullable=False,
            comment='Topics in private chats fee rate (k2, typically 0.15)'),
        sa.Column('commission_k3',
                  sa.Numeric(precision=5, scale=4),
                  nullable=False,
                  comment='Owner margin rate (k3, configurable, default 0.0)'),
        sa.Column('status',
                  postgresql.ENUM('completed',
                                  'refunded',
                                  name='paymentstatus',
                                  create_type=False),
                  nullable=False,
                  server_default='completed',
                  comment='Payment status (completed or refunded)'),
        sa.Column('refunded_at',
                  sa.DateTime(timezone=True),
                  nullable=True,
                  comment='When payment was refunded (NULL if not refunded)'),
        sa.Column(
            'invoice_payload',
            sa.String(128),
            nullable=False,
            comment=
            'Invoice payload from sendInvoice (format: topup_<user_id>_<timestamp>_<stars>)'
        ),
        sa.Column('created_at',
                  sa.DateTime(timezone=True),
                  server_default=sa.func.now(),
                  nullable=False),
        sa.Column('updated_at',
                  sa.DateTime(timezone=True),
                  server_default=sa.func.now(),
                  onupdate=sa.func.now(),
                  nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('telegram_payment_charge_id'),
        sa.CheckConstraint('stars_amount > 0', name='check_stars_positive'),
        sa.CheckConstraint('nominal_usd_amount > 0',
                           name='check_nominal_positive'),
        sa.CheckConstraint('credited_usd_amount > 0',
                           name='check_credited_positive'),
        sa.CheckConstraint('commission_k1 >= 0 AND commission_k1 <= 1',
                           name='check_k1_range'),
        sa.CheckConstraint('commission_k2 >= 0 AND commission_k2 <= 1',
                           name='check_k2_range'),
        sa.CheckConstraint('commission_k3 >= 0 AND commission_k3 <= 1',
                           name='check_k3_range'),
        sa.CheckConstraint(
            'commission_k1 + commission_k2 + commission_k3 <= 1.0001',
            name='check_total_commission'),
    )
    op.create_index('idx_payments_user_id', 'payments', ['user_id'])
    op.create_index('idx_payments_telegram_payment_charge_id',
                    'payments', ['telegram_payment_charge_id'],
                    unique=True)
    op.create_index('idx_payments_status', 'payments', ['status'])
    op.create_index('idx_payments_user_created', 'payments',
                    ['user_id', 'created_at'])
    op.create_index('idx_payments_status_refunded', 'payments',
                    ['status', 'refunded_at'])

    # 4. Create OperationType enum
    operation_type_enum = postgresql.ENUM('payment',
                                          'usage',
                                          'refund',
                                          'admin_topup',
                                          name='operationtype',
                                          create_type=False)
    operation_type_enum.create(op.get_bind(), checkfirst=True)

    # 5. Create balance_operations table
    op.create_table(
        'balance_operations',
        sa.Column('id',
                  sa.Integer(),
                  autoincrement=True,
                  nullable=False,
                  comment='Operation ID'),
        sa.Column('user_id',
                  sa.BigInteger(),
                  nullable=False,
                  comment='User whose balance was modified'),
        sa.Column('operation_type',
                  postgresql.ENUM('payment',
                                  'usage',
                                  'refund',
                                  'admin_topup',
                                  name='operationtype',
                                  create_type=False),
                  nullable=False,
                  comment='Type of balance operation'),
        sa.Column('amount',
                  sa.Numeric(precision=10, scale=4),
                  nullable=False,
                  comment='Amount added (positive) or deducted (negative)'),
        sa.Column('balance_before',
                  sa.Numeric(precision=10, scale=4),
                  nullable=False,
                  comment='User balance BEFORE this operation'),
        sa.Column('balance_after',
                  sa.Numeric(precision=10, scale=4),
                  nullable=False,
                  comment='User balance AFTER this operation'),
        sa.Column('related_payment_id',
                  sa.Integer(),
                  nullable=True,
                  comment='Related payment (for PAYMENT/REFUND operations)'),
        sa.Column(
            'related_message_id',
            sa.Integer(),
            nullable=True,
            comment=
            'Related message_id (for USAGE operations - which request caused charge, no FK due to composite key)'
        ),
        sa.Column(
            'admin_user_id',
            sa.BigInteger(),
            nullable=True,
            comment='Admin who performed the topup (for ADMIN_TOPUP only)'),
        sa.Column(
            'description',
            sa.Text(),
            nullable=False,
            comment=
            'Human-readable operation description with all relevant details'),
        sa.Column('created_at',
                  sa.DateTime(timezone=True),
                  server_default=sa.func.now(),
                  nullable=False),
        sa.Column('updated_at',
                  sa.DateTime(timezone=True),
                  server_default=sa.func.now(),
                  onupdate=sa.func.now(),
                  nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['related_payment_id'], ['payments.id'],
                                ondelete='SET NULL'),
        # Note: No FK for related_message_id because messages table has composite PK (chat_id, message_id)
        sa.ForeignKeyConstraint(['admin_user_id'], ['users.id'],
                                ondelete='SET NULL'),
    )
    op.create_index('idx_operations_user_id', 'balance_operations', ['user_id'])
    op.create_index('idx_operations_operation_type', 'balance_operations',
                    ['operation_type'])
    op.create_index('idx_operations_related_payment_id', 'balance_operations',
                    ['related_payment_id'])
    op.create_index('idx_operations_related_message_id', 'balance_operations',
                    ['related_message_id'])
    op.create_index('idx_operations_user_created', 'balance_operations',
                    ['user_id', 'created_at'])
    op.create_index('idx_operations_type_created', 'balance_operations',
                    ['operation_type', 'created_at'])


def downgrade() -> None:
    """Revert migration: Remove payment system tables and balance column."""
    # Drop tables in reverse order (respect foreign keys)
    op.drop_table('balance_operations')
    op.drop_table('payments')

    # Drop enums
    op.execute("DROP TYPE operationtype")
    op.execute("DROP TYPE paymentstatus")

    # Drop balance column from users
    op.drop_index('idx_users_balance', table_name='users')
    op.drop_column('users', 'balance')
