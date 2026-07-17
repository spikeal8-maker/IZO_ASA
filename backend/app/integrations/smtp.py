"""SMTP transport for transactional application email."""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from html import unescape
import re
from typing import Callable, Protocol


class SmtpError(RuntimeError):
    pass


class SmtpClient(Protocol):
    def __enter__(self): ...
    def __exit__(self, exc_type, exc_value, traceback): ...
    def login(self, user: str, password: str): ...
    def noop(self): ...
    def send_message(self, msg: EmailMessage): ...


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    username: str
    password: str
    use_ssl: bool = True
    timeout_seconds: float = 20.0


@dataclass(frozen=True)
class SmtpMessage:
    to: str
    subject: str
    html: str
    sender_name: str
    sender_email: str


def _validate_config(config: SmtpConfig) -> None:
    if not config.host.strip():
        raise SmtpError("Не указан SMTP-сервер.")
    if not (1 <= config.port <= 65535):
        raise SmtpError("Некорректный SMTP-порт.")
    if not config.username.strip():
        raise SmtpError("Не указан почтовый ящик.")
    if not config.password:
        raise SmtpError("Не указан пароль SMTP.")


def _default_client(config: SmtpConfig) -> SmtpClient:
    if config.use_ssl:
        return smtplib.SMTP_SSL(
            config.host,
            config.port,
            timeout=config.timeout_seconds,
            context=ssl.create_default_context(),
        )
    return smtplib.SMTP(config.host, config.port, timeout=config.timeout_seconds)


def _smtp_error(exc: BaseException) -> SmtpError:
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return SmtpError(
            "Mail.ru не принял почтовый ящик или пароль приложения. "
            "Обычный пароль от почты не подходит: создайте пароль для внешнего приложения с доступом SMTP."
        )
    if isinstance(exc, (TimeoutError, OSError)):
        return SmtpError("Не удалось подключиться к почтовому серверу.")
    return SmtpError("Почтовый сервер отклонил запрос.")


def verify_smtp_connection(
    config: SmtpConfig,
    *,
    client_factory: Callable[[SmtpConfig], SmtpClient] = _default_client,
) -> None:
    _validate_config(config)
    try:
        with client_factory(config) as client:
            client.login(config.username, config.password)
            client.noop()
    except SmtpError:
        raise
    except (smtplib.SMTPException, TimeoutError, OSError) as exc:
        raise _smtp_error(exc) from exc


def _plain_text(html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    return unescape(re.sub(r"<[^>]+>", "", text)).strip()


def send_smtp_email(
    config: SmtpConfig,
    message: SmtpMessage,
    *,
    client_factory: Callable[[SmtpConfig], SmtpClient] = _default_client,
) -> str:
    _validate_config(config)
    email = EmailMessage()
    message_id = make_msgid(domain=message.sender_email.partition("@")[2] or None)
    email["Message-ID"] = message_id
    email["From"] = formataddr((message.sender_name, message.sender_email))
    email["To"] = message.to
    email["Subject"] = message.subject
    email.set_content(_plain_text(message.html))
    email.add_alternative(message.html, subtype="html")
    try:
        with client_factory(config) as client:
            client.login(config.username, config.password)
            client.send_message(email)
    except SmtpError:
        raise
    except (smtplib.SMTPException, TimeoutError, OSError) as exc:
        raise _smtp_error(exc) from exc
    return message_id
