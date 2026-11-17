
from fastapi import Depends, FastAPI, HTTPException, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client import CONTENT_TYPE_LATEST

from app.config import settings
from app.database import get_db

from app.api.webhooks import router as webhooks_router
from app.api.events import router as events_router
from app.api.deliveries import router as deliveries_router
from app.api_trucking import router as trucking_router
from app.api_loads import router as loads_router
from app.api.auth import router as auth_router

from app.observability.metrics import DatabaseMetricsCollector
from app.observability.logging_config import configure_logging


configure_logging()


app = FastAPI(
    title=settings.app_name,
    description="Reliable event storage and webhook delivery platform",
    version="1.0.0",
)


# Existing application routes
app.include_router(webhooks_router)
app.include_router(events_router)
app.include_router(deliveries_router)
app.include_router(trucking_router)
app.include_router(loads_router)

# Authentication routes
app.include_router(auth_router)


@app.get("/")
def root():
    return {
        "message": "Reliable Webhook Delivery Engine API",
        "docs": "/docs",
        "metrics": "/metrics",
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/health/database")
def database_health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))

        return {
            "status": "connected",
            "database": "PostgreSQL",
        }

    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database connection failed",
        ) from exc


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics(db: Session = Depends(get_db)):

    try:
        registry = CollectorRegistry()

        registry.register(
            DatabaseMetricsCollector(db)
        )

        metrics_data = generate_latest(registry)

        return Response(
            content=metrics_data,
            media_type=CONTENT_TYPE_LATEST,
        )

    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Unable to collect application metrics",
        ) from exc
