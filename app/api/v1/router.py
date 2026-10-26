from fastapi import APIRouter

from app.api.v1.endpoints import annotations, auth, health, metadata_queries, standard_fields

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(annotations.router)
api_router.include_router(metadata_queries.router)
api_router.include_router(standard_fields.router)

# 后续按 DEV-TASKS 逐步接入：
#   V0.5  domains / tags / dicts / todos / changes
#   V1.0  security / subscriptions / dashboard / admin / semantic
