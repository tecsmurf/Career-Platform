"""
Email provider errors.

Each error carries a stable machine `code`, a user-safe `user_message` and the
HTTP status the API should use. Raw library/server messages are NEVER exposed:
`str(err)` returns the safe message only.

Note: mailbox authentication failures are 400, never 401 — 401 is reserved for
Career Platform (JWT) authentication, and the frontend logs the user out on it.
"""


class EmailProviderError(Exception):
    code = "provider_error"
    http_status = 502
    default_message = "Something went wrong while talking to your email provider."

    def __init__(self, user_message: str | None = None):
        self.user_message = user_message or self.default_message
        super().__init__(self.user_message)

    def __str__(self) -> str:
        return self.user_message


class InvalidAccountDetails(EmailProviderError):
    code = "invalid_input"
    http_status = 400
    default_message = "Some of the connection details are invalid."


class UnsafeHostError(EmailProviderError):
    code = "unsafe_host"
    http_status = 400
    default_message = (
        "That mail server address isn't allowed. Use your provider's public IMAP "
        "host name (for example imap.gmail.com)."
    )


class HostResolutionError(EmailProviderError):
    code = "host_not_found"
    http_status = 400
    default_message = "We couldn't find that mail server. Check the IMAP host name."


class AuthenticationFailed(EmailProviderError):
    code = "auth_failed"
    http_status = 400
    default_message = (
        "Your email provider rejected these credentials. Check the email address and "
        "app password."
    )


class TLSVerificationFailed(EmailProviderError):
    code = "tls_failed"
    http_status = 502
    default_message = (
        "A secure connection to your email provider couldn't be verified, so no "
        "credentials were sent."
    )


class ProviderTimeout(EmailProviderError):
    code = "timeout"
    http_status = 504
    default_message = "Your email provider took too long to respond. Try again in a moment."


class ProviderUnavailable(EmailProviderError):
    code = "provider_unreachable"
    http_status = 502
    default_message = "Your email provider could not be reached. Try again in a few minutes."


class MailboxError(EmailProviderError):
    code = "mailbox_error"
    http_status = 502
    default_message = "Your mailbox could not be read."
