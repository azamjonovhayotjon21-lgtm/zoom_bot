import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from config import ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET

TASHKENT = ZoneInfo("Asia/Tashkent")


def get_zoom_token() -> str:
    """Zoom Server-to-Server OAuth token oladi."""
    response = requests.post(
        "https://zoom.us/oauth/token",
        params={"grant_type": "account_credentials", "account_id": ZOOM_ACCOUNT_ID},
        auth=(ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET)
    )
    response.raise_for_status()
    return response.json()["access_token"]


def create_zoom_meeting(
    topic: str = "Meeting",
    start_dt: datetime = None,
    duration: int = 60
) -> dict:
    """
    Yangi Zoom meeting yaratadi.
    start_dt berilmasa — hozirdan 2 daqiqa keyin boshlanadi.
    """
    token = get_zoom_token()

    if start_dt is None:
        start_dt = datetime.now(TASHKENT) + timedelta(minutes=2)

    # Zoom UTC formatda kutadi
    start_utc = start_dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")

    payload = {
        "topic": topic,
        "type": 2,
        "start_time": start_utc,
        "duration": duration,
        "timezone": "Asia/Tashkent",
        "settings": {
            "join_before_host": True,
            "waiting_room": False,
            "auto_recording": "cloud",
            "local_recording": True,
            "host_video": True,
            "participant_video": True,
            "mute_upon_entry": False,
        }
    }

    response = requests.post(
        "https://api.zoom.us/v2/users/me/meetings",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json=payload
    )
    response.raise_for_status()
    return response.json()
