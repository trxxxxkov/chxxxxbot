"""Service factory for dependency injection.

Eliminates duplicate service initialization across handlers.
Provides lazy-loaded repositories and services with shared session.

Usage:
    services = ServiceFactory(session)
    await services.balance.charge_user(user_id, amount, ...)
    user = await services.users.get_by_id(user_id)

Benefits:
    - Single point of service/repository creation
    - Repositories created once per request (lazy)
    - Easy to mock in tests
    - Consistent initialization

NO __init__.py - use direct import:
    from services.factory import ServiceFactory
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db.repositories.balance_operation_repository import \
        BalanceOperationRepository
    from db.repositories.chat_repository import ChatRepository
    from db.repositories.message_repository import MessageRepository
    from db.repositories.payment_repository import PaymentRepository
    from db.repositories.thread_repository import ThreadRepository
    from db.repositories.tool_call_repository import ToolCallRepository
    from db.repositories.user_file_repository import UserFileRepository
    from db.repositories.user_repository import UserRepository
    from services.balance_service import BalanceService
    from services.payment_service import PaymentService
    from sqlalchemy.ext.asyncio import AsyncSession


class ServiceFactory:  # pylint: disable=too-many-instance-attributes
    """Factory for creating service instances with shared session.

    All repositories and services are lazy-loaded on first access.
    This avoids unnecessary initialization when only some are needed.

    Example:
        async def handle_message(message: Message, session: AsyncSession):
            services = ServiceFactory(session)

            # Only UserRepository is created
            user = await services.users.get_by_id(message.from_user.id)

            # Now BalanceService is created (with its dependencies)
            await services.balance.charge_user(user.id, amount, "API call")
    """

    def __init__(self, session: "AsyncSession") -> None:
        """Initialize factory with database session.

        Args:
            session: SQLAlchemy async session for all operations.
        """
        self._session = session

        # Lazy-loaded repositories (created on first access)
        self._user_repo: "UserRepository | None" = None
        self._chat_repo: "ChatRepository | None" = None
        self._thread_repo: "ThreadRepository | None" = None
        self._message_repo: "MessageRepository | None" = None
        self._user_file_repo: "UserFileRepository | None" = None
        self._payment_repo: "PaymentRepository | None" = None
        self._balance_op_repo: "BalanceOperationRepository | None" = None
        self._tool_call_repo: "ToolCallRepository | None" = None

        # Lazy-loaded services
        self._balance_service: "BalanceService | None" = None
        self._payment_service: "PaymentService | None" = None

    # =========================================================================
    # Repositories
    # =========================================================================

    @property
    def users(self) -> "UserRepository":
        """Get UserRepository instance."""
        if self._user_repo is None:
            from db.repositories.user_repository import UserRepository
            self._user_repo = UserRepository(self._session)
        return self._user_repo

    @property
    def chats(self) -> "ChatRepository":
        """Get ChatRepository instance."""
        if self._chat_repo is None:
            from db.repositories.chat_repository import ChatRepository
            self._chat_repo = ChatRepository(self._session)
        return self._chat_repo

    @property
    def threads(self) -> "ThreadRepository":
        """Get ThreadRepository instance."""
        if self._thread_repo is None:
            from db.repositories.thread_repository import ThreadRepository
            self._thread_repo = ThreadRepository(self._session)
        return self._thread_repo

    @property
    def messages(self) -> "MessageRepository":
        """Get MessageRepository instance."""
        if self._message_repo is None:
            from db.repositories.message_repository import MessageRepository
            self._message_repo = MessageRepository(self._session)
        return self._message_repo

    @property
    def files(self) -> "UserFileRepository":
        """Get UserFileRepository instance."""
        if self._user_file_repo is None:
            from db.repositories.user_file_repository import UserFileRepository
            self._user_file_repo = UserFileRepository(self._session)
        return self._user_file_repo

    @property
    def payments(self) -> "PaymentRepository":
        """Get PaymentRepository instance."""
        if self._payment_repo is None:
            from db.repositories.payment_repository import PaymentRepository
            self._payment_repo = PaymentRepository(self._session)
        return self._payment_repo

    @property
    def balance_ops(self) -> "BalanceOperationRepository":
        """Get BalanceOperationRepository instance."""
        if self._balance_op_repo is None:
            from db.repositories.balance_operation_repository import \
                BalanceOperationRepository
            self._balance_op_repo = BalanceOperationRepository(self._session)
        return self._balance_op_repo

    @property
    def tool_calls(self) -> "ToolCallRepository":
        """Get ToolCallRepository instance."""
        if self._tool_call_repo is None:
            from db.repositories.tool_call_repository import ToolCallRepository
            self._tool_call_repo = ToolCallRepository(self._session)
        return self._tool_call_repo

    # =========================================================================
    # Services
    # =========================================================================

    @property
    def balance(self) -> "BalanceService":
        """Get BalanceService instance.

        BalanceService requires UserRepository and BalanceOperationRepository,
        which are automatically created if not already initialized.
        """
        if self._balance_service is None:
            from services.balance_service import BalanceService
            self._balance_service = BalanceService(
                self._session,
                self.users,
                self.balance_ops,
            )
        return self._balance_service

    @property
    def payment(self) -> "PaymentService":
        """Get PaymentService instance.

        PaymentService requires multiple repositories and BalanceService.
        """
        if self._payment_service is None:
            from services.payment_service import PaymentService
            self._payment_service = PaymentService(
                self._session,
                self.users,
                self.payments,
                self.balance,
            )
        return self._payment_service
