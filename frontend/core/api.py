
import logging

import requests

from django.conf import settings


logger = logging.getLogger(__name__)


def api_request(request, method, endpoint, **kwargs):
    """
    Send an authenticated request to FastAPI.

    JWT is read from the Django server-side session.
    Returns (data, error).
    """

    base_url = settings.FASTAPI_BASE_URL.rstrip("/")
    endpoint = "/" + endpoint.lstrip("/")
    url = f"{base_url}{endpoint}"

    # Copy headers to avoid modifying the caller's dictionary.
    headers = dict(kwargs.pop("headers", {}))

    token = request.session.get("access_token")

    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.request(
            method=method.upper(),
            url=url,
            headers=headers,
            timeout=15,
            **kwargs,
        )

        if not response.ok:
            try:
                error_data = response.json()

                if isinstance(error_data, dict):
                    error = error_data.get(
                        "detail",
                        response.text or f"HTTP {response.status_code}",
                    )
                else:
                    error = response.text or f"HTTP {response.status_code}"

            except ValueError:
                error = response.text or f"HTTP {response.status_code}"

            # Clear expired authentication details.
            if response.status_code == 401 and token:
                request.session.pop("access_token", None)
                request.session.pop("api_user", None)
                request.session.pop("api_role", None)

                return None, "Your session has expired. Please log in again."

            # Format FastAPI validation errors.
            if isinstance(error, list):
                error = "; ".join(
                    str(item.get("msg", item))
                    if isinstance(item, dict)
                    else str(item)
                    for item in error
                )

            return None, str(error)

        if not response.content:
            return {}, None

        try:
            return response.json(), None
        except ValueError:
            return response.text, None

    except requests.RequestException:
        logger.exception(
            "FastAPI request failed: %s %s",
            method,
            endpoint,
        )
        return None, "Unable to connect to the backend. Please try again."


def get_api_list(request, endpoint):
    """Fetch a list from FastAPI using the authenticated session."""

    data, error = api_request(request, "GET", endpoint)

    if error:
        return [], error

    if isinstance(data, list):
        return data, None

    if isinstance(data, dict):
        for key in ("items", "results", "data"):
            if isinstance(data.get(key), list):
                return data[key], None

    return [], None
