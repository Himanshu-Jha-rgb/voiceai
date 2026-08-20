import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from livekit import api

load_dotenv()

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="School Voice AI Agent — Token Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_SCHEMA = {
    "lang_mode": ("policy", "sarvam"),
    "preemptive": ("1", "0", "true", "false"),
    "llm_provider": ("sarvam", "openai", "groq"),
    # Model is free-form (providers add models faster than catalogs update).
    "llm_model": ("*",),
    "persona": ("*",),
}


def _session_attributes(**kwargs) -> dict[str, str]:
    """Normalize frontend-provided session settings into participant attributes."""
    attrs: dict[str, str] = {}
    for key, allowed in _SCHEMA.items():
        raw = kwargs.get(key)
        if raw is None:
            continue
        value = str(raw).strip().lower()
        if "*" in allowed or value in [a.lower() for a in allowed]:
            attrs[key] = value
    if "preemptive" in attrs:
        attrs["preemptive"] = "1" if attrs["preemptive"] in ("1", "true") else "0"
    return attrs


@app.get("/token")
async def get_token(
    room_name: str | None = None,
    participant_name: str | None = None,
    lang_mode: str | None = None,
    preemptive: str | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    persona: str | None = None,
):
    """Generate a LiveKit access token for the frontend to join a room."""
    # A completed agent session is not reused by LiveKit's React useSession
    # hook. Give each browser call a fresh room unless a caller deliberately
    # requests a named room (for example, an externally orchestrated session).
    room_name = room_name or f"school-voice-{uuid.uuid4().hex[:12]}"
    if participant_name is None:
        participant_name = f"user-{uuid.uuid4().hex[:8]}"

    token = api.AccessToken(
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    ).with_identity(participant_name).with_name(participant_name).with_attributes(
        _session_attributes(
            lang_mode=lang_mode,
            preemptive=preemptive,
            llm_provider=llm_provider,
            llm_model=llm_model,
            persona=persona,
        )
    ).with_grants(
        api.VideoGrants(
            room_join=True,
            room=room_name,
        )
    )

    return {
        "token": token.to_jwt(),
        "url": os.environ["LIVEKIT_URL"],
        "participant_name": participant_name,
    }


@app.post("/token")
async def post_token(body: dict):
    """POST /token endpoint compatible with LiveKit TokenSource.endpoint().

    The frontend's TokenSource sends a protojson TokenSourceRequest — the
    `participant_attributes` map carries the per-session settings (lang_mode,
    preemptive) and is forwarded into the JWT so the agent can read them.
    """
    # useSession refreshes the token after `end()` specifically so the next
    # connection can join a new room and receive a new agent dispatch.
    room_name = body.get("room_name") or f"school-voice-{uuid.uuid4().hex[:12]}"
    participant_name = body.get("participant_name") or f"user-{uuid.uuid4().hex[:8]}"
    attributes = _session_attributes(**body.get("participant_attributes") or {})

    token = api.AccessToken(
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    ).with_identity(participant_name).with_name(participant_name).with_attributes(
        attributes
    ).with_grants(
        api.VideoGrants(
            room_join=True,
            room=room_name,
        )
    )

    return {
        "server_url": os.environ["LIVEKIT_URL"],
        "participant_token": token.to_jwt(),
    }


# Mount the built frontend
# Ensure the directory exists (it will be created during Docker build)
frontend_path = os.path.join(os.path.dirname(__file__), "frontend/dist")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="static")


@app.exception_handler(404)
async def not_found_exception_handler(request, exc):
    """Catch-all for React Router/SPA fallback."""
    if os.path.exists(os.path.join(frontend_path, "index.html")):
        return FileResponse(os.path.join(frontend_path, "index.html"))
    return {"detail": "Not Found"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
