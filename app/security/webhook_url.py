
import ipaddress
import os
import socket

from urllib.parse import urlsplit


class WebhookURLValidationError(ValueError):
    """Raised when a webhook URL is unsafe."""


def validate_webhook_url(url: str) -> str:
    """
    Validate webhook destinations against common SSRF targets.

    HTTP is permitted only for loopback destinations when explicitly
    enabled for local development. External destinations require HTTPS.
    Private and reserved destinations remain blocked.
    """

    allow_local_http = (
        os.getenv("ALLOW_LOCAL_HTTP_WEBHOOKS", "false").lower()
        == "true"
    )

    try:
        parsed = urlsplit(url)

        if parsed.scheme not in ("http", "https"):
            raise WebhookURLValidationError(
                "Only HTTP and HTTPS webhook URLs are supported."
            )

        if not parsed.hostname:
            raise WebhookURLValidationError(
                "Webhook URL must contain a hostname."
            )

        if parsed.username or parsed.password:
            raise WebhookURLValidationError(
                "Webhook URLs must not contain embedded credentials."
            )

        if parsed.fragment:
            raise WebhookURLValidationError(
                "Webhook URLs must not contain fragments."
            )

        hostname = parsed.hostname.rstrip(".").lower()

        if not hostname:
            raise WebhookURLValidationError(
                "Webhook hostname is invalid."
            )

        port = parsed.port
        if port is not None and not (1 <= port <= 65535):
            raise WebhookURLValidationError(
                "Webhook URL contains an invalid port."
            )

        is_localhost_name = (
            hostname == "localhost"
            or hostname.endswith(".localhost")
        )

        try:
            literal_ip = ipaddress.ip_address(hostname)
            addresses = [literal_ip]

        except ValueError:
            try:
                resolved = socket.getaddrinfo(
                    hostname,
                    port or (443 if parsed.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
            except socket.gaierror as exc:
                raise WebhookURLValidationError(
                    "Webhook hostname could not be resolved."
                ) from exc

            addresses = list({
                ipaddress.ip_address(result[4][0])
                for result in resolved
            })

        if not addresses:
            raise WebhookURLValidationError(
                "Webhook hostname has no valid IP addresses."
            )

        # Local HTTP exception: explicitly enabled, and every resolved
        # address must be loopback. Mixed public/private DNS is rejected.
        is_loopback_only = all(
            address.is_loopback for address in addresses
        )

        local_http_allowed = (
            allow_local_http
            and parsed.scheme == "http"
            and (is_localhost_name or is_loopback_only)
            and is_loopback_only
        )

        if parsed.scheme != "https" and not local_http_allowed:
            raise WebhookURLValidationError(
                "HTTPS is required except for explicitly enabled "
                "loopback development destinations."
            )

        for address in addresses:
            if address.is_link_local:
                raise WebhookURLValidationError(
                    "Link-local webhook destinations are not allowed."
                )

            if not address.is_global and not local_http_allowed:
                raise WebhookURLValidationError(
                    "Private, loopback, reserved, and non-public "
                    "webhook destinations are not allowed."
                )

        return url

    except WebhookURLValidationError:
        raise

    except (ValueError, OSError) as exc:
        raise WebhookURLValidationError(
            "Invalid webhook URL."
        ) from exc
