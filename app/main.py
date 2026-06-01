from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import companies, health, suppression


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Lagentry Lead Engine", version="0.1.0", lifespan=lifespan)

app.include_router(health.router)
app.include_router(companies.router, prefix="/api/v1")
app.include_router(suppression.router, prefix="/api/v1")
