from __future__ import annotations

import smtplib

import pytest

from app.integrations.smtp import SmtpConfig, SmtpError, SmtpMessage, send_smtp_email, verify_smtp_connection


class FakeClient:
    def __init__(self, *, auth_error: bool = False):
        self.auth_error = auth_error
        self.login_args = None
        self.message = None
        self.noop_called = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def login(self, user, password):
        if self.auth_error:
            raise smtplib.SMTPAuthenticationError(535, b"denied")
        self.login_args = (user, password)

    def noop(self):
        self.noop_called = True

    def send_message(self, message):
        self.message = message


def config() -> SmtpConfig:
    return SmtpConfig("smtp.mail.ru", 465, "mail@alikinas.ru", "application-password")


def test_verify_smtp_connection_logs_in_and_checks_server():
    client = FakeClient()
    verify_smtp_connection(config(), client_factory=lambda _config: client)
    assert client.login_args == ("mail@alikinas.ru", "application-password")
    assert client.noop_called is True


def test_verify_smtp_connection_returns_human_auth_error():
    with pytest.raises(SmtpError, match="логин или пароль приложения"):
        verify_smtp_connection(config(), client_factory=lambda _config: FakeClient(auth_error=True))


def test_send_smtp_email_builds_plain_and_html_message():
    client = FakeClient()
    message_id = send_smtp_email(
        config(),
        SmtpMessage(
            to="user@example.test",
            subject="Код подтверждения",
            html="<p>Ваш код: <b>123456</b></p>",
            sender_name="ИЗО АСА",
            sender_email="mail@alikinas.ru",
        ),
        client_factory=lambda _config: client,
    )
    assert message_id.startswith("<") and message_id.endswith(">")
    assert client.message["To"] == "user@example.test"
    assert client.message["From"] == "ИЗО АСА <mail@alikinas.ru>"
    assert client.message.is_multipart()
    assert "123456" in client.message.get_body(preferencelist=("plain",)).get_content()
    assert "<b>123456</b>" in client.message.get_body(preferencelist=("html",)).get_content()
