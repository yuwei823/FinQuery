from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .config import settings


app = FastAPI(
    title="FinQuery Studio API",
    version="1.0.0",
    description="面向金融市场数据分析的自然语言问数服务",
    docs_url=None if settings.public_mode else "/docs",
    redoc_url=None if settings.public_mode else "/redoc",
    openapi_url=None if settings.public_mode else "/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
