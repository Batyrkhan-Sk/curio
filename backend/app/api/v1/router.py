from fastapi import APIRouter

from app.api.v1 import admin, ai, cards, discovery, me, search, telegram
from app.core.config import settings

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(discovery.router)
api_router.include_router(cards.router)
api_router.include_router(cards.categories_router)
api_router.include_router(search.router)
api_router.include_router(ai.router)
api_router.include_router(me.router)
# Always mounted, even with no bot token: the routes answer 503 with a reason,
# which is a far better debugging experience than a 404 on the webhook URL you
# just handed to Telegram.
api_router.include_router(telegram.router)
# The admin endpoints reseed, ingest and reindex, and they are unauthenticated.
# That is fine on localhost and unacceptable the moment the app is reachable
# from anywhere else — a tunnel, a LAN, a deployment — so exposing them is an
# explicit decision rather than the default that happens to be convenient.
if settings.admin_api_enabled:
    api_router.include_router(admin.router)
