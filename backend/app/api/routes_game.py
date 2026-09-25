from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_session
from app.api.routes_auth import require_telegram_id
from app.config import settings
from app.services.game_service import registry, get_or_create_user, BOT_GAME_CHAT_PREFIX
from app.services.telegram_bot_api import verify_group_membership
from app.game_engine.engine import EngineError
from app.game_engine.state import Phase
from app.websocket.manager import manager
from app.services.checkpoint_service import save_checkpoint

router = APIRouter(prefix="/games", tags=["games"])


class CreateGameRequest(BaseModel):
    display_name: str
    chat_id: str | None = None


class JoinGameRequest(BaseModel):
    display_name: str


class ForChatRequest(BaseModel):
    chat_id: str
    display_name: str
    # The caller's Telegram profile photo, taken from the verified initData
    # the client already logged in with (see /auth/telegram). Sent up here
    # so the lobby grid can show real faces instead of initial-letter
    # placeholders; optional, because Telegram omits it for users who have
    # no photo or who hide it.
    avatar_url: str | None = None


class ActionRequest(BaseModel):
    target_id: str | None = None


@router.post("")
async def create_game(body: CreateGameRequest, telegram_user_id: int = Depends(require_telegram_id)):
    from app.services.access_control import require_subscription
    await require_subscription(telegram_user_id)
    engine = registry.create(host_telegram_id=telegram_user_id, host_name=body.display_name)
    return {"game_id": engine.state.game_id, "player_id": engine.state.host_id}


@router.post("/for-chat")
async def get_or_create_for_chat(body: ForChatRequest, telegram_user_id: int = Depends(require_telegram_id)):
    """The real entry point for the product: there is no 'create a match'
    button anywhere in the client. The bot posts one join button per group;
    everyone who taps it lands here. The first tapper's request creates the
    group's match and becomes host (able to start it, or it auto-starts at
    25 players); everyone after that joins the same match idempotently.

    Before any of that: Telegram itself has to confirm this caller is
    actually a member of chat_id right now. initData only proves who they
    are, not which group they're claiming to sit in — without this, anyone
    could type a stranger's group id into the Mini App URL."""
    from app.services.access_control import require_subscription
    await require_subscription(telegram_user_id)
    if body.chat_id.startswith(BOT_GAME_CHAT_PREFIX):
        # A practice match seated with AI players, created from the admin
        # panel — there is no Telegram group behind this chat_id, so there
        # is nothing getChatMember could verify. The check it replaces is
        # stricter, not weaker: only a bot admin may enter, and only the
        # one keyed to their own user id, so this can't be used to walk
        # into somebody else's practice game.
        if telegram_user_id not in settings.admin_telegram_ids:
            raise HTTPException(403, "Bu o'yin faqat bot admini uchun")
        if body.chat_id != f"{BOT_GAME_CHAT_PREFIX}{telegram_user_id}":
            raise HTTPException(403, "Bu sizning test o'yiningiz emas")
    elif not await verify_group_membership(body.chat_id, telegram_user_id):
        raise HTTPException(403, "Siz bu Telegram guruhning a'zosi emassiz")
    engine, created = registry.get_or_create_for_chat(
        body.chat_id, telegram_user_id, body.display_name, body.avatar_url,
    )
    player_id = engine.find_player_id(telegram_user_id)
    if player_id is None:
        if engine.state.phase != Phase.LOBBY:
            raise HTTPException(409, "Bu guruh uchun o'yin allaqachon boshlangan")
        try:
            player_id = engine.add_player(telegram_user_id, body.display_name, body.avatar_url)
        except EngineError as e:
            raise HTTPException(400, str(e))
        await manager.broadcast_state(engine.state.game_id, engine)
        await save_checkpoint(engine)
    elif body.avatar_url and engine.state.players[player_id].avatar_url != body.avatar_url:
        # Rejoin after a reconnect (or a host whose engine row predates this
        # field): refresh the stored avatar, since Telegram's photo URLs
        # expire and the old one may already be a broken image.
        engine.state.players[player_id].avatar_url = body.avatar_url
        await manager.broadcast_state(engine.state.game_id, engine)
        await save_checkpoint(engine)
    return {
        "game_id": engine.state.game_id,
        "player_id": player_id,
        "is_host": player_id == engine.state.host_id,
        "created": created,
    }


@router.post("/{game_id}/join")
async def join_game(game_id: str, body: JoinGameRequest, telegram_user_id: int = Depends(require_telegram_id)):
    from app.services.access_control import require_subscription
    await require_subscription(telegram_user_id)
    try:
        engine = registry.get(game_id)
        player_id = engine.add_player(telegram_user_id, body.display_name)
    except KeyError:
        raise HTTPException(404, "Game no longer exists")
    except EngineError as e:
        raise HTTPException(400, str(e))
    await manager.broadcast_state(game_id, engine)
    await save_checkpoint(engine)
    return {"game_id": game_id, "player_id": player_id}


@router.post("/{game_id}/start")
async def start_game(game_id: str, telegram_user_id: int = Depends(require_telegram_id)):
    try:
        engine = registry.get(game_id)
        player_id = engine.find_player_id(telegram_user_id)
        if not player_id:
            raise HTTPException(403, "You are not in this game")
        engine.start_game(player_id)
    except KeyError:
        raise HTTPException(404, "Game no longer exists")
    except EngineError as e:
        raise HTTPException(400, str(e))
    await manager.broadcast_state(game_id, engine)
    await save_checkpoint(engine)
    return {"ok": True}


@router.get("/{game_id}/state")
async def get_state(game_id: str, telegram_user_id: int = Depends(require_telegram_id)):
    """REST fallback for reconnection before the WebSocket handshake completes."""
    try:
        engine = registry.get(game_id)
    except KeyError:
        raise HTTPException(404, "Game no longer exists")
    player_id = engine.find_player_id(telegram_user_id)
    if not player_id:
        raise HTTPException(403, "You are not in this game")
    return engine.get_player_view(player_id)


@router.post("/{game_id}/kick/{target_id}")
async def kick_player(game_id: str, target_id: str, telegram_user_id: int = Depends(require_telegram_id)):
    try:
        engine = registry.get(game_id)
        host_id = engine.find_player_id(telegram_user_id)
        engine.kick_player(host_id, target_id)
    except KeyError:
        raise HTTPException(404, "Game no longer exists")
    except EngineError as e:
        raise HTTPException(400, str(e))
    await manager.broadcast_state(game_id, engine)
    await save_checkpoint(engine)
    return {"ok": True}
