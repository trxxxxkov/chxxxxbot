"""Regression tests for timezone-aware datetime columns.

This module ensures all DateTime columns in SQLAlchemy models use
timezone=True to prevent 'offset-naive and offset-aware' comparison errors.

Bug history:
- 2026-01-11: uploaded_at in user_files was DateTime without timezone=True
  causing TypeError when comparing with datetime.now(timezone.utc)
"""

import pytest
from sqlalchemy import DateTime
from sqlalchemy import inspect as sa_inspect

from db.models.base import Base
from db.models.chat import Chat
from db.models.message import Message
from db.models.thread import Thread
from db.models.user import User
from db.models.user_file import UserFile
from db.models.payment import Payment
from db.models.balance_operation import BalanceOperation


class TestDateTimeTimezoneConsistency:
    """Ensure all DateTime columns are timezone-aware.

    Regression tests for bug where some DateTime columns lacked timezone=True,
    causing comparisons between timezone-naive and timezone-aware datetimes
    to fail with:
        TypeError: can't subtract offset-naive and offset-aware datetimes
    """

    # All models to check
    ALL_MODELS = [
        User,
        Chat,
        Thread,
        Message,
        UserFile,
        Payment,
        BalanceOperation,
    ]

    def get_datetime_columns(self, model_class):
        """Get all DateTime columns from a model.

        Args:
            model_class: SQLAlchemy model class.

        Returns:
            Dict of column_name -> column_type for DateTime columns.
        """
        mapper = sa_inspect(model_class)
        datetime_columns = {}

        for column in mapper.columns:
            if isinstance(column.type, DateTime):
                datetime_columns[column.name] = column.type

        return datetime_columns

    @pytest.mark.parametrize("model_class", ALL_MODELS)
    def test_all_datetime_columns_have_timezone(self, model_class):
        """Verify all DateTime columns use timezone=True.

        This is a critical check - any DateTime without timezone=True
        will cause runtime errors when comparing with timezone-aware
        datetimes from datetime.now(timezone.utc).

        Args:
            model_class: SQLAlchemy model to check.
        """
        datetime_columns = self.get_datetime_columns(model_class)

        non_tz_columns = []
        for col_name, col_type in datetime_columns.items():
            if not col_type.timezone:
                non_tz_columns.append(col_name)

        if non_tz_columns:
            pytest.fail(
                f"Model {model_class.__name__} has DateTime columns "
                f"without timezone=True: {non_tz_columns}. "
                f"All DateTime columns must use DateTime(timezone=True) "
                f"to prevent timezone comparison errors."
            )

    def test_user_file_uploaded_at_has_timezone(self):
        """Regression test for uploaded_at timezone.

        Bug 2026-01-11: uploaded_at was DateTime without timezone=True,
        while expires_at had timezone=True. This caused errors in
        format_time_ago() when comparing datetimes.
        """
        mapper = sa_inspect(UserFile)

        uploaded_at = None
        expires_at = None

        for column in mapper.columns:
            if column.name == "uploaded_at":
                uploaded_at = column.type
            elif column.name == "expires_at":
                expires_at = column.type

        assert uploaded_at is not None, "uploaded_at column not found"
        assert expires_at is not None, "expires_at column not found"

        assert uploaded_at.timezone is True, (
            "uploaded_at must have timezone=True (regression bug fix)"
        )
        assert expires_at.timezone is True, (
            "expires_at must have timezone=True"
        )

    def test_base_mixin_columns_have_timezone(self):
        """Verify TimestampMixin columns (created_at, updated_at) have timezone.

        All models inherit from TimestampMixin via Base, so these columns
        should consistently use timezone=True across all tables.
        Verified via User model which inherits TimestampMixin.
        """
        # Check via User model which inherits TimestampMixin
        datetime_columns = self.get_datetime_columns(User)

        # created_at and updated_at should be present and have timezone
        assert 'created_at' in datetime_columns, "created_at not found in User"
        assert 'updated_at' in datetime_columns, "updated_at not found in User"

        assert datetime_columns['created_at'].timezone is True, (
            "TimestampMixin.created_at must have timezone=True"
        )
        assert datetime_columns['updated_at'].timezone is True, (
            "TimestampMixin.updated_at must have timezone=True"
        )
