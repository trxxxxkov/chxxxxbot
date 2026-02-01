"""Baseline migration - creates all tables from current schema.

This is the initial migration for the project after alpha testing.
All previous migrations have been consolidated into this single baseline.

Revision ID: 001
Create Date: 2026-02-01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables."""
    # Create ENUM types
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE filesource AS ENUM ('user', 'assistant');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE filetype AS ENUM ('image', 'pdf', 'document', 'audio', 'voice', 'video', 'generated');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE messagerole AS ENUM ('USER', 'ASSISTANT', 'SYSTEM');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE operationtype AS ENUM ('payment', 'usage', 'refund', 'admin_topup');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE paymentstatus AS ENUM ('completed', 'refunded');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # Create users table
    op.create_table(
        'users', sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('is_bot', sa.Boolean(), nullable=False),
        sa.Column('first_name', sa.Text(), nullable=False),
        sa.Column('last_name', sa.Text(), nullable=True),
        sa.Column('username', sa.Text(), nullable=True),
        sa.Column('language_code', sa.String(10), nullable=True),
        sa.Column('is_premium', sa.Boolean(), nullable=False),
        sa.Column('added_to_attachment_menu', sa.Boolean(), nullable=False),
        sa.Column('model_id', sa.String(100), nullable=False),
        sa.Column('custom_prompt', sa.Text(), nullable=True),
        sa.Column('balance',
                  sa.Numeric(10, 4),
                  server_default='0.1000',
                  nullable=False),
        sa.Column('message_count',
                  sa.BigInteger(),
                  server_default='0',
                  nullable=False),
        sa.Column('total_tokens_used',
                  sa.BigInteger(),
                  server_default='0',
                  nullable=False),
        sa.Column('first_seen_at',
                  sa.DateTime(timezone=True),
                  server_default=sa.func.now(),
                  nullable=False),
        sa.Column('last_seen_at',
                  sa.DateTime(timezone=True),
                  server_default=sa.func.now(),
                  nullable=False),
        sa.Column('created_at',
                  sa.DateTime(timezone=True),
                  server_default=sa.func.now(),
                  nullable=False),
        sa.Column('updated_at',
                  sa.DateTime(timezone=True),
                  server_default=sa.func.now(),
                  nullable=False), sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username'))

    # Create chats table
    op.create_table(
        'chats', sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('type', sa.String(20), nullable=False),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('username', sa.Text(), nullable=True),
        sa.Column('first_name', sa.Text(), nullable=True),
        sa.Column('last_name', sa.Text(), nullable=True),
        sa.Column('is_forum', sa.Boolean(), nullable=False),
        sa.Column('created_at',
                  sa.DateTime(timezone=True),
                  server_default=sa.func.now(),
                  nullable=False),
        sa.Column('updated_at',
                  sa.DateTime(timezone=True),
                  server_default=sa.func.now(),
                  nullable=False), sa.PrimaryKeyConstraint('id'))

    # Create threads table
    op.create_table(
        'threads',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('thread_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('files_context', sa.Text(), nullable=True),
        sa.Column('needs_topic_naming',
                  sa.Boolean(),
                  server_default='false',
                  nullable=False),
        sa.Column('is_cleared',
                  sa.Boolean(),
                  server_default='false',
                  nullable=False),
        sa.Column('created_at',
                  sa.DateTime(timezone=True),
                  server_default=sa.func.now(),
                  nullable=False),
        sa.Column('updated_at',
                  sa.DateTime(timezone=True),
                  server_default=sa.func.now(),
                  nullable=False), sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('chat_id',
                            'user_id',
                            'thread_id',
                            name='uq_threads_chat_user_thread'))
    op.create_index('idx_threads_chat_user', 'threads', ['chat_id', 'user_id'])
    op.create_index('idx_threads_thread_id', 'threads', ['thread_id'])

    # Create messages table
    op.create_table(
        'messages', sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('message_id', sa.Integer(), nullable=False),
        sa.Column('thread_id', sa.BigInteger(), nullable=True),
        sa.Column('from_user_id', sa.BigInteger(), nullable=True),
        sa.Column('date', sa.Integer(), nullable=False),
        sa.Column('edit_date', sa.Integer(), nullable=True),
        sa.Column('role',
                  postgresql.ENUM('USER',
                                  'ASSISTANT',
                                  'SYSTEM',
                                  name='messagerole',
                                  create_type=False),
                  nullable=False),
        sa.Column('text_content', sa.Text(), nullable=True),
        sa.Column('caption', sa.Text(), nullable=True),
        sa.Column('reply_to_message_id', sa.Integer(), nullable=True),
        sa.Column('reply_snippet', sa.Text(), nullable=True),
        sa.Column('reply_sender_display', sa.Text(), nullable=True),
        sa.Column('quote_data', postgresql.JSONB(), nullable=True),
        sa.Column('forward_origin', postgresql.JSONB(), nullable=True),
        sa.Column('sender_display', sa.Text(), nullable=True),
        sa.Column('edit_count',
                  sa.Integer(),
                  server_default='0',
                  nullable=False),
        sa.Column('original_content', sa.Text(), nullable=True),
        sa.Column('media_group_id', sa.Text(), nullable=True),
        sa.Column('has_photos', sa.Boolean(), nullable=False, default=False),
        sa.Column('has_documents', sa.Boolean(), nullable=False, default=False),
        sa.Column('has_voice', sa.Boolean(), nullable=False, default=False),
        sa.Column('has_video', sa.Boolean(), nullable=False, default=False),
        sa.Column('attachment_count', sa.Integer(), nullable=False, default=0),
        sa.Column('attachments',
                  postgresql.JSONB(),
                  server_default="'[]'",
                  nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('cache_creation_input_tokens', sa.Integer(), nullable=True),
        sa.Column('cache_read_input_tokens', sa.Integer(), nullable=True),
        sa.Column('thinking_tokens', sa.Integer(), nullable=True),
        sa.Column('thinking_blocks', sa.Text(), nullable=True),
        sa.Column('model_id', sa.String(64), nullable=True),
        sa.Column('created_at', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('chat_id', 'message_id'),
        sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['thread_id'], ['threads.id'],
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['from_user_id'], ['users.id'],
                                ondelete='SET NULL'))
    op.create_index('idx_messages_thread',
                    'messages', ['thread_id'],
                    postgresql_where=sa.text('thread_id IS NOT NULL'))
    op.create_index('idx_messages_from_user',
                    'messages', ['from_user_id'],
                    postgresql_where=sa.text('from_user_id IS NOT NULL'))
    op.create_index('idx_messages_date', 'messages', ['date'])
    op.create_index('idx_messages_role', 'messages', ['role'])
    op.create_index('idx_messages_media_group',
                    'messages', ['media_group_id'],
                    postgresql_where=sa.text('media_group_id IS NOT NULL'))
    op.create_index('idx_messages_has_photos',
                    'messages', ['has_photos'],
                    postgresql_where=sa.text('has_photos IS TRUE'))
    op.create_index('idx_messages_has_documents',
                    'messages', ['has_documents'],
                    postgresql_where=sa.text('has_documents IS TRUE'))
    op.create_index('idx_messages_has_voice',
                    'messages', ['has_voice'],
                    postgresql_where=sa.text('has_voice IS TRUE'))
    op.create_index('idx_messages_attachments_gin',
                    'messages', ['attachments'],
                    postgresql_using='gin',
                    postgresql_ops={'attachments': 'jsonb_path_ops'})

    # Create payments table
    op.create_table(
        'payments',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('telegram_payment_charge_id', sa.String(255), nullable=False),
        sa.Column('stars_amount', sa.Integer(), nullable=False),
        sa.Column('nominal_usd_amount', sa.Numeric(10, 4), nullable=False),
        sa.Column('credited_usd_amount', sa.Numeric(10, 4), nullable=False),
        sa.Column('commission_k1', sa.Numeric(5, 4), nullable=False),
        sa.Column('commission_k2', sa.Numeric(5, 4), nullable=False),
        sa.Column('commission_k3', sa.Numeric(5, 4), nullable=False),
        sa.Column('status',
                  postgresql.ENUM('completed',
                                  'refunded',
                                  name='paymentstatus',
                                  create_type=False),
                  nullable=False),
        sa.Column('refunded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('invoice_payload', sa.String(128), nullable=False),
        sa.Column('created_at',
                  sa.DateTime(timezone=True),
                  server_default=sa.func.now(),
                  nullable=False),
        sa.Column('updated_at',
                  sa.DateTime(timezone=True),
                  server_default=sa.func.now(),
                  nullable=False), sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
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
            name='check_total_commission'))
    op.create_index('ix_payments_user_id', 'payments', ['user_id'])
    op.create_index('ix_payments_telegram_payment_charge_id',
                    'payments', ['telegram_payment_charge_id'],
                    unique=True)
    op.create_index('ix_payments_status', 'payments', ['status'])
    op.create_index('idx_payments_user_created', 'payments',
                    ['user_id', 'created_at'])
    op.create_index('idx_payments_status_refunded', 'payments',
                    ['status', 'refunded_at'])

    # Create balance_operations table
    op.create_table(
        'balance_operations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('operation_type',
                  postgresql.ENUM('payment',
                                  'usage',
                                  'refund',
                                  'admin_topup',
                                  name='operationtype',
                                  create_type=False),
                  nullable=False),
        sa.Column('amount', sa.Numeric(10, 4), nullable=False),
        sa.Column('balance_before', sa.Numeric(10, 4), nullable=False),
        sa.Column('balance_after', sa.Numeric(10, 4), nullable=False),
        sa.Column('related_payment_id', sa.Integer(), nullable=True),
        sa.Column('related_message_id', sa.Integer(), nullable=True),
        sa.Column('admin_user_id', sa.BigInteger(), nullable=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('created_at',
                  sa.DateTime(timezone=True),
                  server_default=sa.func.now(),
                  nullable=False),
        sa.Column('updated_at',
                  sa.DateTime(timezone=True),
                  server_default=sa.func.now(),
                  nullable=False), sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['related_payment_id'], ['payments.id'],
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['admin_user_id'], ['users.id'],
                                ondelete='SET NULL'))
    op.create_index('ix_balance_operations_user_id', 'balance_operations',
                    ['user_id'])
    op.create_index('ix_balance_operations_operation_type',
                    'balance_operations', ['operation_type'])
    op.create_index('ix_balance_operations_related_payment_id',
                    'balance_operations', ['related_payment_id'])
    op.create_index('ix_balance_operations_related_message_id',
                    'balance_operations', ['related_message_id'])
    op.create_index('idx_operations_user_created', 'balance_operations',
                    ['user_id', 'created_at'])
    op.create_index('idx_operations_type_created', 'balance_operations',
                    ['operation_type', 'created_at'])

    # Create user_files table
    op.create_table(
        'user_files',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('message_id', sa.BigInteger(), nullable=False),
        sa.Column('telegram_file_id', sa.String(), nullable=True),
        sa.Column('telegram_file_unique_id', sa.String(), nullable=True),
        sa.Column('claude_file_id', sa.String(), nullable=False),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('file_type',
                  postgresql.ENUM('image',
                                  'pdf',
                                  'document',
                                  'audio',
                                  'voice',
                                  'video',
                                  'generated',
                                  name='filetype',
                                  create_type=False),
                  nullable=False),
        sa.Column('mime_type', sa.String(), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('uploaded_at',
                  sa.DateTime(timezone=True),
                  server_default=sa.func.now(),
                  nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('source',
                  postgresql.ENUM('user',
                                  'assistant',
                                  name='filesource',
                                  create_type=False),
                  nullable=False),
        sa.Column('upload_context', sa.String(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id'), sa.UniqueConstraint('claude_file_id'))
    op.create_index('idx_user_files_message_id', 'user_files', ['message_id'])
    op.create_index('idx_user_files_claude_file_id',
                    'user_files', ['claude_file_id'],
                    unique=True)
    op.create_index('idx_user_files_expires_at', 'user_files', ['expires_at'])
    op.create_index('idx_user_files_file_type', 'user_files', ['file_type'])

    # Create tool_calls table
    op.create_table(
        'tool_calls',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('thread_id', sa.BigInteger(), nullable=True),
        sa.Column('message_id', sa.Integer(), nullable=True),
        sa.Column('tool_name', sa.String(64), nullable=False),
        sa.Column('model_id', sa.String(64), nullable=False),
        sa.Column('input_tokens',
                  sa.Integer(),
                  server_default='0',
                  nullable=False),
        sa.Column('output_tokens',
                  sa.Integer(),
                  server_default='0',
                  nullable=False),
        sa.Column('cache_read_tokens',
                  sa.Integer(),
                  server_default='0',
                  nullable=False),
        sa.Column('cache_creation_tokens',
                  sa.Integer(),
                  server_default='0',
                  nullable=False),
        sa.Column('cost_usd', sa.Numeric(12, 6), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('success',
                  sa.Boolean(),
                  server_default='true',
                  nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at',
                  sa.DateTime(timezone=True),
                  server_default=sa.func.now(),
                  nullable=False), sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['thread_id'], ['threads.id'],
                                ondelete='SET NULL'))
    op.create_index('idx_tool_calls_user', 'tool_calls', ['user_id'])
    op.create_index('idx_tool_calls_chat', 'tool_calls', ['chat_id'])
    op.create_index('idx_tool_calls_created', 'tool_calls', ['created_at'])
    op.create_index('idx_tool_calls_tool_name', 'tool_calls', ['tool_name'])


def downgrade() -> None:
    """Drop all tables."""
    op.drop_table('tool_calls')
    op.drop_table('user_files')
    op.drop_table('balance_operations')
    op.drop_table('payments')
    op.drop_table('messages')
    op.drop_table('threads')
    op.drop_table('chats')
    op.drop_table('users')

    op.execute('DROP TYPE IF EXISTS paymentstatus')
    op.execute('DROP TYPE IF EXISTS operationtype')
    op.execute('DROP TYPE IF EXISTS messagerole')
    op.execute('DROP TYPE IF EXISTS filetype')
    op.execute('DROP TYPE IF EXISTS filesource')
