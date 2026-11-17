
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="Webhook Failure Test Receiver")


@app.get("/health")
def health():
    return {"status": "failure_receiver_ready"}


@app.post("/fail")
async def fail_webhook():
    return JSONResponse(
        status_code=500,
        content={
            "status": "failed",
            "message": "Intentional HTTP 500 response for retry testing",
        },
    )
