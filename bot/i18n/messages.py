"""Translation messages for bot interface.

Structure: MESSAGES[key] = {"en": "English text", "ru": "Russian text"}

Keys use dot notation for namespacing:
- common.* - Common messages (errors, warnings)
- start.* - /start and /help commands
- payment.* - /pay, /refund, /balance, /paysupport commands
- balance.* - Balance check middleware messages
- model.* - /model command and model selection
- personality.* - /personality command
- admin.* - /topup, /set_margin, /clear commands
"""

from typing import Dict

# Type alias for message dictionary
MessageDict = Dict[str, Dict[str, str]]

MESSAGES: MessageDict = {
    # =========================================================================
    # Common messages
    # =========================================================================
    "common.unable_to_identify_user": {
        "en": "⚠️ Unable to identify user.",
        "ru": "⚠️ Не удалось определить пользователя.",
    },
    "common.unable_to_identify_user_or_chat": {
        "en": "⚠️ Unable to identify user or chat.",
        "ru": "⚠️ Не удалось определить пользователя или чат.",
    },
    "common.user_not_found": {
        "en": "⚠️ User not found",
        "ru": "⚠️ Пользователь не найден",
    },
    "common.invalid_callback": {
        "en": "⚠️ Invalid callback data",
        "ru": "⚠️ Неверные данные",
    },
    "common.send_text_message": {
        "en": "⚠️ Please send text message",
        "ru": "⚠️ Пожалуйста, отправьте текстовое сообщение",
    },

    # =========================================================================
    # /start and /help commands
    # =========================================================================
    "start.welcome_new": {
        "en": "👋 Welcome!",
        "ru": "👋 Добро пожаловать!",
    },
    "start.welcome_back": {
        "en": "👋 Welcome back!",
        "ru": "👋 С возвращением!",
    },
    "start.message": {
        "en": ("{greeting} I'm an LLM bot.\n\n"
               "Available commands:\n"
               "/start - Show this message\n"
               "/help - Get help\n\n"
               "Send me any message and I'll echo it back!"),
        "ru": ("{greeting} Я бот с ИИ.\n\n"
               "Доступные команды:\n"
               "/start - Показать это сообщение\n"
               "/help - Получить справку\n\n"
               "Отправьте мне любое сообщение, и я отвечу!"),
    },
    "help.message": {
        "en": ("🤖 *Help*\n\n"
               "*Commands:*\n"
               "/start - Start the bot\n"
               "/help - Show this help message\n\n"
               "*Usage:*\n"
               "Just send me any text message and I'll echo it back.\n\n"
               "This is a minimal bot implementation. "
               "LLM integration coming soon!"),
        "ru": ("🤖 *Справка*\n\n"
               "*Команды:*\n"
               "/start - Запустить бота\n"
               "/help - Показать эту справку\n\n"
               "*Использование:*\n"
               "Просто отправьте мне любое текстовое сообщение.\n\n"
               "Это минимальная версия бота. "
               "Интеграция с LLM скоро появится!"),
    },

    # =========================================================================
    # Payment - /pay command
    # =========================================================================
    "payment.topup_title": {
        "en": ("💰 <b>Top-up your balance</b>\n\n"
               "Choose a Stars package to purchase balance.\n"
               "You'll receive USD balance after commissions.\n\n"
               "💡 Use /balance to check your current balance"),
        "ru": ("💰 <b>Пополнить баланс</b>\n\n"
               "Выберите пакет Stars для покупки баланса.\n"
               "Вы получите баланс в USD после комиссий.\n\n"
               "💡 Используйте /balance для проверки баланса"),
    },
    "payment.custom_amount_button": {
        "en": "✏️ Custom amount ({min}-{max}⭐)",
        "ru": "✏️ Своя сумма ({min}-{max}⭐)",
    },
    "payment.enter_custom_amount": {
        "en": ("✏️ <b>Enter custom Stars amount</b>\n\n"
               "Amount must be between {min} and {max} Stars.\n\n"
               "Type the amount and send:"),
        "ru": ("✏️ <b>Введите количество Stars</b>\n\n"
               "Сумма должна быть от {min} до {max} Stars.\n\n"
               "Введите число и отправьте:"),
    },
    "payment.invalid_not_number": {
        "en": "❌ Please send a number (text message).",
        "ru": "❌ Пожалуйста, отправьте число (текстовое сообщение).",
    },
    "payment.invalid_number": {
        "en": "❌ Invalid input. Please enter a valid number.",
        "ru": "❌ Неверный ввод. Пожалуйста, введите число.",
    },
    "payment.amount_out_of_range": {
        "en": ("❌ Amount must be between {min} and {max} Stars.\n\n"
               "Please try again:"),
        "ru": ("❌ Сумма должна быть от {min} до {max} Stars.\n\n"
               "Попробуйте ещё раз:"),
    },
    "payment.invoice_error": {
        "en": "❌ Failed to create invoice. Please try again later.",
        "ru": "❌ Не удалось создать счёт. Попробуйте позже.",
    },
    "payment.invalid_amount": {
        "en": "Invalid amount",
        "ru": "Неверная сумма",
    },
    "payment.invalid_invoice": {
        "en": "Invalid invoice. Please try again.",
        "ru": "Неверный счёт. Попробуйте ещё раз.",
    },
    "payment.invalid_currency": {
        "en": "Invalid currency. Only Telegram Stars accepted.",
        "ru": "Неверная валюта. Принимаются только Telegram Stars.",
    },
    "payment.success": {
        "en": (
            "✅ <b>Payment successful!</b>\n\n"
            "💰 Added: <b>${credited_usd}</b>\n"
            "🔋 New balance: <b>${new_balance}</b>\n\n"
            "🆔 <b>Transaction ID:</b>\n"
            "<code>{transaction_id}</code>\n\n"
            "💡 <b>Save this Transaction ID for refunds.</b>\n"
            "Use <code>/refund &lt;transaction_id&gt;</code> within 30 days if needed."
        ),
        "ru": (
            "✅ <b>Оплата успешна!</b>\n\n"
            "💰 Зачислено: <b>${credited_usd}</b>\n"
            "🔋 Новый баланс: <b>${new_balance}</b>\n\n"
            "🆔 <b>ID транзакции:</b>\n"
            "<code>{transaction_id}</code>\n\n"
            "💡 <b>Сохраните ID транзакции для возврата.</b>\n"
            "Используйте <code>/refund &lt;transaction_id&gt;</code> в течение 30 дней."
        ),
    },
    "payment.processing_error": {
        "en": ("❌ Payment processing error. Contact support: /paysupport\n\n"
               "Your Transaction ID:\n"
               "<code>{transaction_id}</code>"),
        "ru": (
            "❌ Ошибка обработки платежа. Обратитесь в поддержку: /paysupport\n\n"
            "Ваш ID транзакции:\n"
            "<code>{transaction_id}</code>"),
    },

    # =========================================================================
    # Payment - /refund command
    # =========================================================================
    "refund.instructions": {
        "en": ("ℹ️ <b>Refund Instructions</b>\n\n"
               "<b>Usage:</b> <code>/refund &lt;transaction_id&gt;</code>\n\n"
               "<b>Example:</b>\n"
               "<code>/refund telegram_charge_abc123</code>\n\n"
               "💡 Transaction ID is provided when you make a payment.\n"
               "💡 Refunds are available within 30 days.\n"
               "💡 You must have sufficient balance."),
        "ru": (
            "ℹ️ <b>Инструкция по возврату</b>\n\n"
            "<b>Использование:</b> <code>/refund &lt;transaction_id&gt;</code>\n\n"
            "<b>Пример:</b>\n"
            "<code>/refund telegram_charge_abc123</code>\n\n"
            "💡 ID транзакции выдаётся при оплате.\n"
            "💡 Возврат доступен в течение 30 дней.\n"
            "💡 На балансе должно быть достаточно средств."),
    },
    "refund.success": {
        "en": ("✅ <b>Refund successful!</b>\n\n"
               "⭐ Refunded: <b>{stars_amount} Stars</b>\n"
               "💰 Deducted: <b>${usd_amount}</b>\n"
               "🔋 New balance: <b>${new_balance}</b>"),
        "ru": ("✅ <b>Возврат выполнен!</b>\n\n"
               "⭐ Возвращено: <b>{stars_amount} Stars</b>\n"
               "💰 Списано: <b>${usd_amount}</b>\n"
               "🔋 Новый баланс: <b>${new_balance}</b>"),
    },
    "refund.failed": {
        "en": "❌ <b>Refund failed:</b>\n\n{error}",
        "ru": "❌ <b>Ошибка возврата:</b>\n\n{error}",
    },
    "refund.telegram_api_failed": {
        "en": "❌ Refund failed. Please contact support: /paysupport",
        "ru": "❌ Ошибка возврата. Обратитесь в поддержку: /paysupport",
    },
    "refund.processing_error": {
        "en":
            "❌ Refund processing error. Contact support: /paysupport",
        "ru":
            "❌ Ошибка обработки возврата. Обратитесь в поддержку: /paysupport",
    },

    # =========================================================================
    # Payment - /balance command
    # =========================================================================
    "balance.info": {
        "en": ("💰 <b>Your Balance</b>\n\n"
               "Current: <b>${balance}</b>\n\n"
               "📊 <b>Recent history:</b>\n"
               "<pre>{history}</pre>\n\n"
               "💡 Top up: /pay"),
        "ru": ("💰 <b>Ваш баланс</b>\n\n"
               "Текущий: <b>${balance}</b>\n\n"
               "📊 <b>Последние операции:</b>\n"
               "<pre>{history}</pre>\n\n"
               "💡 Пополнить: /pay"),
    },
    "balance.no_history": {
        "en": "No history yet",
        "ru": "История пока пуста",
    },
    "balance.check_error": {
        "en": "❌ Failed to retrieve balance. Please try again.",
        "ru": "❌ Не удалось получить баланс. Попробуйте ещё раз.",
    },

    # =========================================================================
    # Payment - /paysupport command
    # =========================================================================
    "paysupport.info": {
        "en": (
            "💬 <b>Payment Support</b>\n\n"
            "If you have issues with payments, refunds, or balance:\n\n"
            "<b>1.</b> Check your balance: /balance\n"
            "<b>2.</b> Review refund policy:\n"
            "   • Maximum 30 days since payment\n"
            "   • Sufficient balance required\n"
            "<b>3.</b> For refunds: <code>/refund &lt;transaction_id&gt;</code>\n\n"
            "📧 <b>Contact:</b> @trxxxxkov\n\n"
            "💡 Transaction IDs are provided after each payment."),
        "ru": (
            "💬 <b>Поддержка по платежам</b>\n\n"
            "Если у вас проблемы с платежами, возвратами или балансом:\n\n"
            "<b>1.</b> Проверьте баланс: /balance\n"
            "<b>2.</b> Условия возврата:\n"
            "   • Не позднее 30 дней с момента оплаты\n"
            "   • На балансе должно быть достаточно средств\n"
            "<b>3.</b> Для возврата: <code>/refund &lt;transaction_id&gt;</code>\n\n"
            "📧 <b>Контакт:</b> @trxxxxkov\n\n"
            "💡 ID транзакции выдаётся после каждой оплаты."),
    },

    # =========================================================================
    # Balance middleware - insufficient balance
    # =========================================================================
    "balance.insufficient": {
        "en": ("❌ <b>Insufficient balance</b>\n\n"
               "Current balance: <b>${balance}</b>\n\n"
               "To use paid features, please top up your balance.\n"
               "Use /pay to purchase balance with Telegram Stars."),
        "ru": ("❌ <b>Недостаточно средств</b>\n\n"
               "Текущий баланс: <b>${balance}</b>\n\n"
               "Для использования платных функций пополните баланс.\n"
               "Используйте /pay для покупки баланса за Telegram Stars."),
    },

    # =========================================================================
    # /model command
    # =========================================================================
    "model.selection_title": {
        "en": "🤖 Model Selection\n\n",
        "ru": "🤖 Выбор модели\n\n",
    },
    "model.current_model": {
        "en": "**Current model:**\n",
        "ru": "**Текущая модель:**\n",
    },
    "model.select_new": {
        "en": "\n\n👇 Claude · Google\n🟢 flagship · 🔵 balanced · 🔵 fast",
        "ru": "\n\n👇 Claude · Google\n🟢 флагман · 🔵 баланс · 🔵 быстрый",
    },
    "model.changed": {
        "en": "✅ **Model changed**\n\n",
        "ru": "✅ **Модель изменена**\n\n",
    },
    "model.changed_to": {
        "en": "Model changed to {model_name}",
        "ru": "Модель изменена на {model_name}",
    },
    "model.not_found": {
        "en": "⚠️ Model '{model_id}' not found",
        "ru": "⚠️ Модель «{model_id}» не найдена",
    },
    "model.invalid_selection": {
        "en": "⚠️ Invalid model selection",
        "ru": "⚠️ Неверный выбор модели",
    },

    # Model info formatting
    "model.info_provider": {
        "en": "Provider: {provider}\n",
        "ru": "Провайдер: {provider}\n",
    },
    "model.info_context": {
        "en": "Context window: {context:,} tokens\n",
        "ru": "Окно контекста: {context:,} токенов\n",
    },
    "model.info_max_output": {
        "en": "Max output: {max_output:,} tokens\n",
        "ru": "Макс. вывод: {max_output:,} токенов\n",
    },
    "model.info_latency": {
        "en": "Latency: {latency}\n\n",
        "ru": "Задержка: {latency}\n\n",
    },
    "model.info_pricing": {
        "en": "💰 Pricing (per million tokens):\n",
        "ru": "💰 Стоимость (за миллион токенов):\n",
    },
    "model.info_input": {
        "en": "  Input: ${price}\n",
        "ru": "  Ввод: ${price}\n",
    },
    "model.info_output": {
        "en": "  Output: ${price}\n",
        "ru": "  Вывод: ${price}\n",
    },
    "model.info_cache_read": {
        "en": "  Cache read: ${price}\n",
        "ru": "  Чтение кэша: ${price}\n",
    },
    "model.info_features": {
        "en": "\n✨ Features: {features}",
        "ru": "\n✨ Возможности: {features}",
    },

    # =========================================================================
    # /personality command
    # =========================================================================
    "personality.title": {
        "en": "🎭 **Personality Settings**\n\n",
        "ru": "🎭 **Настройки личности**\n\n",
    },
    "personality.description": {
        "en": ("Your custom personality instructions will be added to "
               "every conversation with the bot.\n\n"),
        "ru": ("Ваши инструкции по личности будут добавляться "
               "в каждый разговор с ботом.\n\n"),
    },
    "personality.current": {
        "en": "**Current personality:**\n",
        "ru": "**Текущая личность:**\n",
    },
    "personality.not_set": {
        "en": "_No personality set. Using default behavior._",
        "ru": "_Личность не задана. Используется стандартное поведение._",
    },
    "personality.view_title": {
        "en": "🎭 **Your Current Personality:**\n\n",
        "ru": "🎭 **Ваша текущая личность:**\n\n",
    },
    "personality.no_personality_set": {
        "en": "❌ No personality set",
        "ru": "❌ Личность не задана",
    },
    "personality.edit_prompt": {
        "en": ("✏️ **Enter your new personality instructions:**\n\n"
               "Send me a message with your desired personality. "
               "This will be added to every conversation.\n\n"
               "_Send /cancel to abort._"),
        "ru": ("✏️ **Введите новые инструкции личности:**\n\n"
               "Отправьте сообщение с желаемой личностью. "
               "Она будет добавлена в каждый разговор.\n\n"
               "_Отправьте /cancel для отмены._"),
    },
    "personality.text_too_short": {
        "en":
            "⚠️ Personality text too short. Please provide at least 10 characters.",
        "ru":
            "⚠️ Текст личности слишком короткий. Минимум 10 символов.",
    },
    "personality.updated": {
        "en": "✅ **Personality updated successfully!**\n\n",
        "ru": "✅ **Личность успешно обновлена!**\n\n",
    },
    "personality.your_new": {
        "en": "Your new personality:\n",
        "ru": "Ваша новая личность:\n",
    },
    "personality.cleared": {
        "en":
            "🗑️ **Personality cleared**\n\n_Using default behavior now._",
        "ru":
            "🗑️ **Личность очищена**\n\n_Теперь используется стандартное поведение._",
    },
    "personality.cleared_toast": {
        "en": "Personality cleared",
        "ru": "Личность очищена",
    },

    # Personality keyboard buttons
    "personality.btn_view": {
        "en": "👁️ View Current",
        "ru": "👁️ Просмотр",
    },
    "personality.btn_edit": {
        "en": "✏️ Edit",
        "ru": "✏️ Изменить",
    },
    "personality.btn_set_new": {
        "en": "✏️ Set New",
        "ru": "✏️ Задать",
    },
    "personality.btn_clear": {
        "en": "🗑️ Clear",
        "ru": "🗑️ Очистить",
    },
    "personality.btn_cancel": {
        "en": "❌ Cancel",
        "ru": "❌ Отмена",
    },

    # =========================================================================
    # Admin - /topup command
    # =========================================================================
    "admin.unauthorized": {
        "en": "❌ This command is only available to privileged users.",
        "ru": "❌ Эта команда доступна только привилегированным пользователям.",
    },
    "admin.topup_usage": {
        "en": (
            "ℹ️ <b>Admin Balance Adjustment</b>\n\n"
            "<b>Usage:</b> <code>/topup &lt;user_id or @username&gt; &lt;amount&gt;</code>\n\n"
            "<b>Examples:</b>\n"
            "<code>/topup 123456789 10.50</code>  (add $10.50)\n"
            "<code>/topup @username -5.00</code>  (deduct $5.00)\n\n"
            "💡 Positive amount = add to balance\n"
            "💡 Negative amount = deduct from balance"),
        "ru": (
            "ℹ️ <b>Корректировка баланса (админ)</b>\n\n"
            "<b>Использование:</b> <code>/topup &lt;user_id или @username&gt; &lt;сумма&gt;</code>\n\n"
            "<b>Примеры:</b>\n"
            "<code>/topup 123456789 10.50</code>  (добавить $10.50)\n"
            "<code>/topup @username -5.00</code>  (списать $5.00)\n\n"
            "💡 Положительная сумма = пополнение\n"
            "💡 Отрицательная сумма = списание"),
    },
    "admin.invalid_user_id": {
        "en": "❌ Invalid user ID. Must be a number.",
        "ru": "❌ Неверный ID пользователя. Должно быть число.",
    },
    "admin.invalid_amount": {
        "en": "❌ Invalid amount. Must be a number.",
        "ru": "❌ Неверная сумма. Должно быть число.",
    },
    "admin.topup_success": {
        "en": ("✅ <b>Balance adjusted</b>\n\n"
               "<b>Target:</b> {target}\n"
               "<b>{action}:</b> ${amount}\n"
               "<b>Before:</b> ${before}\n"
               "<b>After:</b> ${after}"),
        "ru": ("✅ <b>Баланс изменён</b>\n\n"
               "<b>Пользователь:</b> {target}\n"
               "<b>{action}:</b> ${amount}\n"
               "<b>До:</b> ${before}\n"
               "<b>После:</b> ${after}"),
    },
    "admin.topup_action_added": {
        "en": "Added",
        "ru": "Зачислено",
    },
    "admin.topup_action_deducted": {
        "en": "Deducted",
        "ru": "Списано",
    },
    "admin.topup_failed": {
        "en": "❌ <b>Topup failed:</b>\n\n{error}",
        "ru": "❌ <b>Ошибка пополнения:</b>\n\n{error}",
    },
    "admin.topup_error": {
        "en": "❌ Topup failed. Please try again.",
        "ru": "❌ Ошибка пополнения. Попробуйте ещё раз.",
    },

    # =========================================================================
    # Admin - /set_margin command
    # =========================================================================
    "admin.margin_usage": {
        "en": ("ℹ️ <b>Owner Margin Configuration</b>\n\n"
               "<b>Usage:</b> <code>/set_margin &lt;k3_value&gt;</code>\n\n"
               "<b>Current settings:</b>\n"
               "• k1 (Telegram withdrawal): {k1:.1f}%\n"
               "• k2 (Topics fee): {k2:.1f}%\n"
               "• k3 (Owner margin): {k3:.1f}%\n\n"
               "<b>Constraint:</b> k1 + k2 + k3 ≤ 1.0\n"
               "k3 must be in range [0, {k3_max:.2f}] ({k3_max_pct:.1f}%)\n\n"
               "<b>Example:</b>\n"
               "<code>/set_margin 0.10</code>  (set 10% margin)"),
        "ru": (
            "ℹ️ <b>Настройка маржи владельца</b>\n\n"
            "<b>Использование:</b> <code>/set_margin &lt;k3_value&gt;</code>\n\n"
            "<b>Текущие настройки:</b>\n"
            "• k1 (комиссия Telegram): {k1:.1f}%\n"
            "• k2 (комиссия Topics): {k2:.1f}%\n"
            "• k3 (маржа владельца): {k3:.1f}%\n\n"
            "<b>Ограничение:</b> k1 + k2 + k3 ≤ 1.0\n"
            "k3 должен быть в диапазоне [0, {k3_max:.2f}] ({k3_max_pct:.1f}%)\n\n"
            "<b>Пример:</b>\n"
            "<code>/set_margin 0.10</code>  (установить 10% маржу)"),
    },
    "admin.margin_invalid_value": {
        "en": "❌ Invalid value. Must be a number.",
        "ru": "❌ Неверное значение. Должно быть число.",
    },
    "admin.margin_out_of_range": {
        "en": "❌ k3 must be in range [0, 1], got {value}",
        "ru": "❌ k3 должен быть в диапазоне [0, 1], получено {value}",
    },
    "admin.margin_exceeds_100": {
        "en": ("❌ <b>Total commission exceeds 100%</b>\n\n"
               "k1 + k2 + k3 = {total:.4f} > 1.0\n\n"
               "<b>Maximum k3:</b> {k3_max:.4f} ({k3_max_pct:.1f}%)"),
        "ru": ("❌ <b>Общая комиссия превышает 100%</b>\n\n"
               "k1 + k2 + k3 = {total:.4f} > 1.0\n\n"
               "<b>Максимум k3:</b> {k3_max:.4f} ({k3_max_pct:.1f}%)"),
    },
    "admin.margin_updated": {
        "en": (
            "✅ <b>Owner margin updated</b>\n\n"
            "<b>Old:</b> {old:.1f}%\n"
            "<b>New:</b> {new:.1f}%\n\n"
            "<b>Total commission breakdown:</b>\n"
            "• k1 (Telegram): {k1:.1f}%\n"
            "• k2 (Topics): {k2:.1f}%\n"
            "• k3 (Owner): {k3:.1f}%\n"
            "• <b>Total:</b> {total:.1f}%\n\n"
            "💡 Users will receive <b>{user_gets:.1f}%</b> of nominal Stars value."
        ),
        "ru": (
            "✅ <b>Маржа владельца обновлена</b>\n\n"
            "<b>Было:</b> {old:.1f}%\n"
            "<b>Стало:</b> {new:.1f}%\n\n"
            "<b>Распределение комиссий:</b>\n"
            "• k1 (Telegram): {k1:.1f}%\n"
            "• k2 (Topics): {k2:.1f}%\n"
            "• k3 (Владелец): {k3:.1f}%\n"
            "• <b>Итого:</b> {total:.1f}%\n\n"
            "💡 Пользователи получают <b>{user_gets:.1f}%</b> от номинала Stars."
        ),
    },

    # =========================================================================
    # Admin - /set_cache_subsidy command
    # =========================================================================
    "admin.cache_subsidy_usage": {
        "en": ("📦 <b>Cache Write Subsidy</b>\n\n"
               "<b>Status:</b> {status}\n\n"
               "Usage: /set_cache_subsidy [on|off]\n"
               "• <b>on</b> — Owner absorbs cache write costs\n"
               "• <b>off</b> — Users pay full cost (default)"),
        "ru": (
            "📦 <b>Субсидия записи кэша</b>\n\n"
            "<b>Статус:</b> {status}\n\n"
            "Использование: /set_cache_subsidy [on|off]\n"
            "• <b>on</b> — Владелец покрывает стоимость записи кэша\n"
            "• <b>off</b> — Пользователи платят полную стоимость (по умолчанию)"
        ),
    },
    "admin.cache_subsidy_invalid_value": {
        "en":
            "❌ Invalid value. Use: /set_cache_subsidy [on|off]",
        "ru":
            "❌ Некорректное значение. Используйте: /set_cache_subsidy [on|off]",
    },
    "admin.cache_subsidy_updated": {
        "en": ("✅ <b>Cache write subsidy updated</b>\n\n"
               "<b>Old:</b> {old}\n"
               "<b>New:</b> {new}"),
        "ru": ("✅ <b>Субсидия записи кэша обновлена</b>\n\n"
               "<b>Было:</b> {old}\n"
               "<b>Стало:</b> {new}"),
    },

    # =========================================================================
    # Admin - /clear command
    # =========================================================================
    "clear.no_topics": {
        "en": "ℹ️ No forum topics to delete.",
        "ru": "ℹ️ Нет топиков для удаления.",
    },
    "clear.confirm_delete": {
        "en": ("⚠️ Are you sure you want to delete {count} topics?\n\n"
               "This action cannot be undone."),
        "ru": ("⚠️ Вы уверены, что хотите удалить {count} топиков?\n\n"
               "Это действие нельзя отменить."),
    },
    "clear.confirm_button": {
        "en": "Yes, delete {count} topics",
        "ru": "Да, удалить {count} топиков",
    },
    "clear.requires_admin": {
        "en":
            ("❌ Clearing all topics requires admin rights.\n"
             "💡 Use /clear inside a specific topic to delete only that topic."),
        "ru": (
            "❌ Для удаления всех топиков нужны права администратора.\n"
            "💡 Используйте /clear внутри топика для удаления только этого топика."
        ),
    },
    "clear.no_permission": {
        "en": "You no longer have permission to do this.",
        "ru": "У вас больше нет прав для этого действия.",
    },
    "clear.no_topics_to_delete": {
        "en": "No topics to delete.",
        "ru": "Нет топиков для удаления.",
    },

    # =========================================================================
    # /help command (dynamic)
    # =========================================================================
    "help.header": {
        "en": "🤖 <b>Help</b>\n",
        "ru": "🤖 <b>Справка</b>\n",
    },
    "help.section_basic": {
        "en": "\n📌 <b>Basic</b>\n",
        "ru": "\n📌 <b>Основные</b>\n",
    },
    "help.section_model": {
        "en": "\n🤖 <b>Model &amp; Settings</b>\n",
        "ru": "\n🤖 <b>Модель и настройки</b>\n",
    },
    "help.section_payment": {
        "en": "\n💳 <b>Payment</b>\n",
        "ru": "\n💳 <b>Оплата</b>\n",
    },
    "help.section_admin": {
        "en": "\n🔧 <b>Admin</b>\n",
        "ru": "\n🔧 <b>Администрирование</b>\n",
    },
    "help.contact": {
        "en": "\n💬 Questions? Contact @{username}",
        "ru": "\n💬 Вопросы? Обращайтесь к @{username}",
    },

    # =========================================================================
    # /announce command
    # =========================================================================
    "announce.unauthorized": {
        "en": "❌ This command is only available to privileged users.",
        "ru": "❌ Эта команда доступна только привилегированным пользователям.",
    },
    "announce.usage": {
        "en": (
            "ℹ️ <b>Broadcast</b>\n\n"
            "<b>Usage:</b>\n"
            "<code>/announce</code> — send to all users\n"
            "<code>/announce @user1 123456 @user2</code>"
            " — send to specific users\n\n"
            "After the command, send any message (text, photo, document, etc.) "
            "to broadcast."),
        "ru": (
            "ℹ️ <b>Рассылка</b>\n\n"
            "<b>Использование:</b>\n"
            "<code>/announce</code> — отправить всем\n"
            "<code>/announce @user1 123456 @user2</code>"
            " — отправить конкретным пользователям\n\n"
            "После команды отправьте любое сообщение (текст, фото, документ и т.д.) "
            "для рассылки."),
    },
    "announce.waiting_for_message": {
        "en": "📢 Send a message to broadcast to <b>{count}</b> recipients.",
        "ru": "📢 Отправьте сообщение для рассылки <b>{count}</b> получателям.",
    },
    "announce.waiting_for_message_all": {
        "en": ("📢 Send a message to broadcast to "
               "<b>all users ({count})</b>."),
        "ru": ("📢 Отправьте сообщение для рассылки "
               "<b>всем пользователям ({count})</b>."),
    },
    "announce.user_not_found": {
        "en": "⚠️ User {target} not found",
        "ru": "⚠️ Пользователь {target} не найден",
    },
    "announce.no_valid_targets": {
        "en": "❌ None of the specified recipients were found.",
        "ru": "❌ Ни один из указанных получателей не найден.",
    },
    "announce.confirm": {
        "en": "Send this message to <b>{count}</b> users?",
        "ru": "Отправить это сообщение <b>{count}</b> пользователям?",
    },
    "announce.confirm_button": {
        "en": "Send ✓",
        "ru": "Отправить ✓",
    },
    "announce.cancel_button": {
        "en": "Cancel ✗",
        "ru": "Отмена ✗",
    },
    "announce.cancelled": {
        "en": "📢 Broadcast cancelled.",
        "ru": "📢 Рассылка отменена.",
    },
    "announce.sending": {
        "en": "📢 Broadcasting... {sent}/{total}",
        "ru": "📢 Рассылка... {sent}/{total}",
    },
    "announce.sending_progress": {
        "en": ("📢 Broadcasting... {sent}/{total} ({pct}%)\n"
               "✅ {delivered}  ❌ {failed}"),
        "ru": ("📢 Рассылка... {sent}/{total} ({pct}%)\n"
               "✅ {delivered}  ❌ {failed}"),
    },
    "announce.complete": {
        "en": ("📢 <b>Broadcast complete</b>\n\n"
               "✅ Delivered: {delivered}\n"
               "❌ Failed: {failed}"),
        "ru": ("📢 <b>Рассылка завершена</b>\n\n"
               "✅ Доставлено: {delivered}\n"
               "❌ Ошибок: {failed}"),
    },
    "announce.report_caption": {
        "en": "📊 Broadcast delivery report",
        "ru": "📊 Отчёт о рассылке",
    },
}
