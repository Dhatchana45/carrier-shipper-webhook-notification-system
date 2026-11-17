
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ShipmentEvent, WebhookEndpoint


async def send_event_to_subscribers(
    event: ShipmentEvent,
    db: Session,
) -> list[dict]:
    statement = select(WebhookEndpoint).where(
        WebhookEndpoint.subscribed_events.contains([event.event_type])
    )

    endpoints = db.scalars(statement).all()
    results = []

    payload = {
        "event_id": event.event_id,
        "load_id": event.load_id,
        "event_type": event.event_type,
        "carrier_id": event.carrier_id,
        "shipper_id": event.shipper_id,
        "description": event.description,
        "created_at": event.created_at.isoformat(),
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        for endpoint in endpoints:
            try:
                response = await client.post(
                    endpoint.url,
                    json=payload,
                )

                results.append({
                    "endpoint_id": endpoint.endpoint_id,
                    "status_code": response.status_code,
                    "success": 200 <= response.status_code < 300,
                })

            except httpx.HTTPError as exc:
                results.append({
                    "endpoint_id": endpoint.endpoint_id,
                    "success": False,
                    "error": str(exc),
                })

    return results
