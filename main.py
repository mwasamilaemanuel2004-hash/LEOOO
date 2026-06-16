from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from api.routes import exchange, bots, analytics, users
import uvicorn

app = FastAPI(title="estrading.machine v10", version="10.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return {"status": "ok"}

app.include_router(exchange.router, tags=["Exchange"])
app.include_router(bots.router, tags=["Bots"])
app.include_router(analytics.router, tags=["Analytics"])
app.include_router(users.router, tags=["Users"])

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
