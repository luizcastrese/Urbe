import datetime as dt
import hashlib
import json
import urllib.parse
import urllib.request

from .errors import AppError


BUNNY_API_BASE = "https://video.bunnycdn.com"


def build_signed_embed_url(
    iframe_host,
    library_id,
    video_id,
    embed_token_key,
    expires_in_seconds=300,
    session_tag="",
):
    if not library_id or not video_id:
        raise AppError("Filme sem identificadores Bunny validos.", 400, "INVALID_BUNNY_IDENTIFIERS")

    expires = int(dt.datetime.utcnow().timestamp()) + int(expires_in_seconds)
    base = f"{iframe_host}/embed/{library_id}/{video_id}"

    session_hash = ""
    if session_tag:
        session_hash = hashlib.sha256(str(session_tag).encode("utf-8")).hexdigest()[:24]

    parsed = urllib.parse.urlparse(base)
    query_params = dict(urllib.parse.parse_qsl(parsed.query))

    if not embed_token_key:
        if session_hash:
            query_params["urbe_session"] = session_hash
        url = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query_params)))
        return {
            "embedUrl": url,
            "expiresAt": dt.datetime.utcfromtimestamp(expires).isoformat() + "Z",
            "signed": False,
        }

    signature = hashlib.sha256(f"{embed_token_key}{video_id}{expires}".encode("utf-8")).hexdigest()
    query_params["token"] = signature
    query_params["expires"] = str(expires)
    if session_hash:
        query_params["urbe_session"] = session_hash

    url = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query_params)))
    return {
        "embedUrl": url,
        "expiresAt": dt.datetime.utcfromtimestamp(expires).isoformat() + "Z",
        "signed": True,
    }


def create_bunny_video(api_key, library_id, title, collection_id=None, thumbnail_time=None):
    if not api_key or not library_id:
        raise AppError(
            "Defina BUNNY_STREAM_API_KEY e BUNNY_STREAM_LIBRARY_ID para criar videos via API.",
            400,
            "BUNNY_NOT_CONFIGURED",
        )

    payload = {"title": title or "Novo Filme Urbe"}
    if collection_id:
        payload["collectionId"] = collection_id
    if thumbnail_time is not None:
        try:
            payload["thumbnailTime"] = float(thumbnail_time)
        except (TypeError, ValueError):
            pass

    req = urllib.request.Request(
        f"{BUNNY_API_BASE}/library/{library_id}/videos",
        method="POST",
        headers={
            "AccessKey": api_key,
            "Content-Type": "application/json",
        },
        data=json.dumps(payload).encode("utf-8"),
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        text = error.read().decode("utf-8", errors="replace")
        raise AppError(f"Falha ao criar video na Bunny.net: {text or error.code}", 502, "BUNNY_CREATE_FAILED")
    except urllib.error.URLError as error:
        raise AppError(f"Falha de rede com Bunny.net: {error.reason}", 502, "BUNNY_CREATE_FAILED")

