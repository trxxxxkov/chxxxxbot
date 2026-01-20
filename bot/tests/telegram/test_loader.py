"""Tests for bot and dispatcher loader.

This module contains comprehensive tests for telegram/loader.py,
testing Bot and Dispatcher creation, middleware registration, and
router configuration.

NO __init__.py - use direct import:
    pytest tests/telegram/test_loader.py
"""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from telegram.loader import create_bot
from telegram.loader import create_dispatcher


@pytest.fixture(autouse=True)
def reset_routers():
    """Reset router parent_router between tests.

    This prevents "Router is already attached" errors when
    create_dispatcher() is called multiple times in different tests.

    Phase 1.4+: Includes all routers (start, model, personality, files,
    media_handlers, claude).
    """
    yield
    # After each test, detach routers from their parent
    from telegram.handlers import (
        admin,
        claude,
        edited_message,
        files,
        media_handlers,
        model,
        payment,
        personality,
        start,
    )

    routers = [
        start.router,
        model.router,
        personality.router,
        payment.router,
        admin.router,
        files.router,
        media_handlers.router,
        edited_message.router,
        claude.router,
    ]

    for router in routers:
        if hasattr(router, '_parent_router') and router._parent_router:
            router._parent_router = None


def test_create_bot_valid_token():
    """Test create_bot with valid token.

    Verifies that Bot instance is created with provided token.
    """
    with patch('telegram.loader.Bot') as mock_bot_class, \
         patch('telegram.loader.logger'):

        mock_bot_instance = MagicMock()
        mock_bot_class.return_value = mock_bot_instance

        bot = create_bot("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")

        # Verify Bot() called
        mock_bot_class.assert_called_once()

        # Verify bot instance returned
        assert bot is mock_bot_instance


def test_create_bot_default_properties():
    """Test create_bot sets DefaultBotProperties.

    Verifies ParseMode.HTML is set as default.
    """
    with patch('telegram.loader.Bot') as mock_bot_class, \
         patch('telegram.loader.logger'):

        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode

        create_bot("test_token")

        # Verify call arguments
        call_kwargs = mock_bot_class.call_args[1]
        assert 'token' in call_kwargs
        assert call_kwargs['token'] == "test_token"

        # Verify DefaultBotProperties with HTML
        assert 'default' in call_kwargs
        default_props = call_kwargs['default']
        assert isinstance(default_props, DefaultBotProperties)
        assert default_props.parse_mode == ParseMode.HTML


def test_create_bot_logging():
    """Test that create_bot logs bot creation.

    Verifies logging of bot_created event.
    """
    with patch('telegram.loader.Bot'), \
         patch('telegram.loader.logger') as mock_logger:

        create_bot("test_token")

        # Verify logging
        mock_logger.info.assert_called_once_with("bot_created")


def test_create_bot_returns_bot_type():
    """Test create_bot returns Bot instance.

    Verifies return type is aiogram Bot.
    """
    with patch('telegram.loader.logger'):
        from aiogram import Bot

        # Use real Bot to verify type (will fail to connect but that's ok)
        bot = create_bot("123456:test_token_for_type_check")

        assert isinstance(bot, Bot)


def test_create_dispatcher_structure():
    """Test create_dispatcher creates Dispatcher.

    Verifies Dispatcher instance is created and configured.
    """
    with patch('telegram.loader.logger'):
        dispatcher = create_dispatcher()

        from aiogram import Dispatcher

        assert isinstance(dispatcher, Dispatcher)


def test_create_dispatcher_middleware_order():
    """Test create_dispatcher registers middlewares in correct order.

    Verifies LoggingMiddleware is registered before DatabaseMiddleware.
    """
    with patch('telegram.loader.logger'):
        dispatcher = create_dispatcher()

        # Check middlewares registered
        # dispatcher.update.middleware is an observer that tracks middlewares
        # Note: _middlewares is private but we need it for testing
        middlewares = dispatcher.update.middleware._middlewares

        # Should have 2 middlewares
        assert len(middlewares) >= 2

        # Check types (first is LoggingMiddleware, second is DatabaseMiddleware)
        from telegram.middlewares.database_middleware import DatabaseMiddleware
        from telegram.middlewares.logging_middleware import LoggingMiddleware

        # Find middleware types in order
        middleware_types = [type(m) for m in middlewares]
        logging_index = next((i for i, t in enumerate(middleware_types)
                              if t == LoggingMiddleware), None)
        database_index = next((i for i, t in enumerate(middleware_types)
                               if t == DatabaseMiddleware), None)

        assert logging_index is not None, "LoggingMiddleware not found"
        assert database_index is not None, "DatabaseMiddleware not found"
        assert logging_index < database_index, \
            "LoggingMiddleware should be before DatabaseMiddleware"


def test_create_dispatcher_router_order():
    """Test create_dispatcher registers routers in correct order.

    Phase 2.1+: Verifies all routers registered with claude as catch-all last.
    """
    with patch('telegram.loader.logger'):
        dispatcher = create_dispatcher()

        # Check routers registered
        routers = list(dispatcher.sub_routers)

        # Should have 9 routers (added edited_message)
        assert len(routers) == 9

        # Check router names (order matters - claude must be last)
        router_names = [r.name for r in routers]
        expected = [
            "start", "model", "personality", "payment", "admin", "files",
            "media", "edited_message", "claude"
        ]
        assert router_names == expected, \
            f"Routers should be in order: {expected}"


def test_create_dispatcher_router_names():
    """Test that routers have correct names.

    Phase 2.1+: Verifies all routers present.
    """
    with patch('telegram.loader.logger'):
        dispatcher = create_dispatcher()

        routers = list(dispatcher.sub_routers)
        router_names = [r.name for r in routers]

        # Check all routers present (added edited_message)
        expected_routers = [
            "start", "model", "personality", "payment", "admin", "files",
            "media", "edited_message", "claude"
        ]
        for router_name in expected_routers:
            assert router_name in router_names, \
                f"Router '{router_name}' should be present"


def test_create_dispatcher_logging():
    """Test that create_dispatcher logs dispatcher creation.

    Phase 2.1+: Verifies logging with all router names.
    """
    with patch('telegram.loader.logger') as mock_logger:
        create_dispatcher()

        # Verify logging (9 routers with edited_message)
        expected_routers = [
            "start", "model", "personality", "payment", "admin", "files",
            "media", "edited_message", "claude"
        ]
        mock_logger.info.assert_called_once_with("dispatcher_created",
                                                 routers=expected_routers)


def test_create_dispatcher_returns_type():
    """Test create_dispatcher returns Dispatcher instance.

    Verifies return type.
    """
    with patch('telegram.loader.logger'):
        dispatcher = create_dispatcher()

        from aiogram import Dispatcher

        assert isinstance(dispatcher, Dispatcher)


def test_create_dispatcher_includes_handlers():
    """Test that dispatcher includes handlers from routers.

    Verifies handlers are accessible through routers.
    """
    with patch('telegram.loader.logger'):
        dispatcher = create_dispatcher()

        routers = list(dispatcher.sub_routers)

        # Each router should have handlers
        for router in routers:
            # Check that router has message handlers
            assert hasattr(router, 'message')
            # Router should have registered handlers
            # (exact structure depends on aiogram internals)


def test_create_bot_token_parameter():
    """Test create_bot accepts token parameter.

    Verifies token is passed to Bot constructor.
    """
    with patch('telegram.loader.Bot') as mock_bot_class, \
         patch('telegram.loader.logger'):

        test_token = "987654:XYZ-custom-token"
        create_bot(test_token)

        # Verify token passed
        call_args = mock_bot_class.call_args
        assert call_args[1]['token'] == test_token


def test_create_dispatcher_middleware_registration():
    """Test that both middlewares are registered.

    Verifies LoggingMiddleware and DatabaseMiddleware present.
    """
    with patch('telegram.loader.logger'):
        dispatcher = create_dispatcher()

        from telegram.middlewares.database_middleware import DatabaseMiddleware
        from telegram.middlewares.logging_middleware import LoggingMiddleware

        # Note: _middlewares is private but we need it for testing
        middlewares = dispatcher.update.middleware._middlewares
        middleware_types = [type(m) for m in middlewares]

        assert LoggingMiddleware in middleware_types
        assert DatabaseMiddleware in middleware_types


def test_create_bot_parse_mode_html():
    """Test that create_bot sets ParseMode.HTML.

    Verifies default parse mode configuration.
    """
    with patch('telegram.loader.logger'):
        from aiogram.enums import ParseMode

        # Use valid token format: bot_id:bot_token
        bot = create_bot("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")

        # Check default properties
        assert bot.default is not None
        assert bot.default.parse_mode == ParseMode.HTML
