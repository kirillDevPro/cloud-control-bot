"""Decorator for handling Telegram API errors."""

from functools import wraps
from typing import TypeVar, Callable, Any
import logging

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramNetworkError,
    TelegramServerError,
    TelegramRetryAfter,
    TelegramAPIError,
)

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def handle_telegram_errors(handler: F) -> F:
    """
    Decorator that automatically handles Telegram API errors.

    Handles the following error types:
    - TelegramBadRequest: malformed requests (message is not modified, etc.)
    - TelegramNetworkError: network problems
    - TelegramServerError: errors on Telegram's side
    - TelegramRetryAfter: rate limit exceeded
    - TelegramAPIError: other API errors

    Args:
        handler: Async handler function (command or callback).

    Returns:
        The wrapped function with error handling.

    Example:
        >>> @router.callback_query(F.data == "refresh")
        >>> @handle_telegram_errors
        >>> async def callback_refresh(callback: CallbackQuery):
        ...     await callback.message.edit_text("Updated")
    """

    @wraps(handler)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Invoke the wrapped handler and translate Telegram API exceptions.

        Args:
            *args: Positional arguments forwarded to the handler.
            **kwargs: Keyword arguments forwarded to the handler.

        Returns:
            The handler's return value, or None when a harmless error is
            swallowed (e.g. "message is not modified", "message too long").

        Raises:
            TelegramAPIError: Re-raised for errors that are not silently
                handled (network/server errors, rate limits, and other
                unhandled API or unexpected exceptions).
        """
        handler_name = handler.__name__

        try:
            return await handler(*args, **kwargs)

        except TelegramBadRequest as e:
            error_msg = str(e).lower()

            # Ignore harmless errors (already handled in safe_edit_message)
            if "message is not modified" in error_msg:
                return None

            if "message to edit not found" in error_msg:
                logger.warning(
                    f"Message not found in {handler_name} " "(user deleted the message)"
                )
                return None

            # Handle the "message too long" error
            if "message is too long" in error_msg:
                logger.error(f"Message too long in {handler_name}: {e}")
                # A notification could be sent to the user here
                return None

            # Handle invalid HTML
            if "can't parse" in error_msg or "invalid html" in error_msg:
                logger.error(f"Invalid HTML formatting in {handler_name}: {e}")
                return None

            # Other TelegramBadRequest errors - log and re-raise
            logger.error(f"TelegramBadRequest in {handler_name}: {e}", exc_info=True)
            raise

        except TelegramRetryAfter as e:
            # Rate limiting - log and re-raise for the retry mechanism
            logger.warning(
                f"Rate limit exceeded in {handler_name}. " f"Retry after {e.retry_after} seconds"
            )
            raise

        except TelegramNetworkError as e:
            # Network errors - log
            logger.error(f"Network error in {handler_name}: {e}", exc_info=True)
            raise

        except TelegramServerError as e:
            # Errors on Telegram's side - log
            logger.error(f"Telegram server error in {handler_name}: {e}", exc_info=True)
            raise

        except TelegramAPIError as e:
            # Other Telegram API errors
            logger.error(f"Telegram API error in {handler_name}: {e}", exc_info=True)
            raise

        except Exception as e:
            # Unexpected errors - log with full stack trace
            logger.error(f"Unexpected error in {handler_name}: {e}", exc_info=True)
            raise

    return wrapper  # type: ignore
