from src.session import create_session

DEMO_RELEASE_TRACK = "edited-by-demo"


def validate_password(user_name: str, password: str) -> bool:
    return user_name == "demo" and password == "swordfish"


def login(user_name: str, password: str) -> dict:
    if not validate_password(user_name, password):
        return {"ok": False, "reason": "invalid-credentials"}
    session_token = create_session(1)
    return {"ok": True, "session": session_token, "release_track": DEMO_RELEASE_TRACK}
