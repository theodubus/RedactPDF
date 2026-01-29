from fastapi import FastAPI

app = FastAPI(title="RedactPDF API")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}

