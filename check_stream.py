import os
import json
import requests
import time
from datetime import datetime

CONFIG_FILE = "config.json"
STATE_FILE = "state.json"

# Umgebungsvariablen aus den GitHub Secrets
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
DISCORD_CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID")
TWITCH_CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET")

BASE_API_URL = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages"

HEADERS = {
    "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
    "Content-Type": "application/json"
}

def load_json_file(filepath, default_value):
    if not os.path.exists(filepath):
        return default_value
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4)

def format_duration(seconds):
    if seconds <= 0:
        return "Unbekannt"
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    
    parts = []
    if hours > 0:
        parts.append(f"{hours} Stunde{'n' if hours != 1 else ''}")
    if minutes > 0 or hours == 0: 
        parts.append(f"{minutes} Minute{'n' if minutes != 1 else ''}")
        
    return " und ".join(parts)

def get_twitch_access_token():
    url = f"https://id.twitch.tv/oauth2/token?client_id={TWITCH_CLIENT_ID}&client_secret={TWITCH_CLIENT_SECRET}&grant_type=client_credentials"
    response = requests.post(url)
    if response.status_code == 200:
        return response.json().get("access_token")
    print("❌ Fehler beim Abrufen des Twitch Access Tokens")
    return None

def fetch_twitch_data_batch(streamers):
    logins = [s.get("channel", "").lower() for s in streamers if s.get("channel")]
    if not logins: 
        return {}
    
    token = get_twitch_access_token()
    if not token:
        return {}

    twitch_headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}"
    }
    
    # 1. Live-Streams abrufen
    params = [("user_login", login) for login in logins]
    streams_resp = requests.get("https://api.twitch.tv/helix/streams", headers=twitch_headers, params=params)
    live_streams = streams_resp.json().get("data", [])
    
    if not live_streams:
        return {} 
        
    # 2. Benutzerprofile abrufen (für die Profilbilder)
    live_logins = [s["user_login"] for s in live_streams]
    users_params = [("login", login) for login in live_logins]
    users_resp = requests.get("https://api.twitch.tv/helix/users", headers=twitch_headers, params=users_params)
    users_data = users_resp.json().get("data", [])
    
    user_info = {u["login"]: u["profile_image_url"] for u in users_data}
    
    live_data_map = {}
    
    for stream in live_streams:
        login = stream["user_login"].lower()
        avatar_url = user_info.get(login, "")
        
        # Startzeit konvertieren
        started_at = stream.get("started_at", "") 
        unix_timestamp = 0
        if started_at:
            dt = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
            unix_timestamp = int(dt.timestamp())
            
        tags = stream.get("tags", [])
        formatted_tags = " • ".join(tags[:3]) if tags else ""
        
        thumb_url = stream["thumbnail_url"].replace("{width}", "1920").replace("{height}", "1080")
        thumb_url += f"?t={int(time.time())}"
        
        live_data_map[login] = {
            "is_streaming": True,
            "title": stream["title"],
            "game_name": stream["game_name"],
            "url": f"https://twitch.tv/{login}",
            "thumbnail_url": thumb_url,
            "avatar_url": avatar_url,
            "viewers": stream.get("viewer_count", 0),
            "started_at": unix_timestamp,
            "tags": formatted_tags
        }
        
    return live_data_map

def send_live_notification(streamer_config, stream_data):
    title = stream_data.get("title", "Live Stream!")
    url = stream_data.get("url", "https://twitch.tv")
    game = stream_data.get("game_name", "Just Chatting")
    thumbnail = stream_data.get("thumbnail_url", "")
    avatar = stream_data.get("avatar_url", "")
    viewers = stream_data.get("viewers", 0)
    started_at = stream_data.get("started_at", 0)
    tags = stream_data.get("tags", "")
    
    channel_name = streamer_config.get("channel", "Twitch").title()

    content_parts = []
    if streamer_config.get("ping_role") and streamer_config.get("role_id"):
        content_parts.append(f"<@&{streamer_config['role_id']}>")
        
    custom_text = streamer_config.get("custom_text", "")
    if custom_text:
        content_parts.append(custom_text)
        
    final_content = " ".join(content_parts)
    time_string = f"<t:{started_at}:R>" if started_at else "Jetzt gerade"

    payload = {
        "content": final_content,
        "embeds": [{
            "author": {
                "name": f"{channel_name} ist LIVE!",
                "url": url,
                "icon_url": avatar
            },
            "title": title, 
            "url": url,
            "description": f"*{tags}*" if tags else "", 
            "color": 9520895, 
            "fields": [
                {"name": "🎮 Kategorie", "value": game, "inline": True},
                {"name": "👁️ Zuschauer", "value": str(viewers), "inline": True},
                {"name": "⏱️ Gestartet", "value": time_string, "inline": True}
            ],
            "image": {"url": thumbnail} if thumbnail else {},
        }],
        # NUR DER LIVE BUTTON
        "components": [{
            "type": 1, 
            "components": [
                {"type": 2, "style": 5, "label": "Jetzt zuschauen", "url": url}
            ]
        }]
    }

    response = requests.post(BASE_API_URL, headers=HEADERS, json=payload)
    if response.status_code in [200, 201]:
        print(f"✅ Live-Benachrichtigung gesendet für {streamer_config['id']}")
        return response.json().get("id")
    else:
        print(f"❌ Fehler beim Senden: {response.status_code} - {response.text}")
        return None

def update_offline_message(message_id, started_at_timestamp):
    if not message_id: return

    message_url = f"{BASE_API_URL}/{message_id}"
    get_response = requests.get(message_url, headers=HEADERS)
    
    if get_response.status_code == 200:
        msg_data = get_response.json()
        embeds = msg_data.get("embeds", [])
        
        if embeds:
            embed = embeds[0]
            embed["color"] = 8421504 # Grau
            
            # Titel/Author anpassen (Emoji entfernt)
            if "author" in embed:
                old_name = embed["author"].get("name", "")
                clean_name = old_name.replace(" ist LIVE!", "")
                embed["author"]["name"] = f"{clean_name} ist offline"
            
            # Dauer berechnen
            duration_text = ""
            if started_at_timestamp:
                current_time = int(time.time())
                duration_seconds = current_time - started_at_timestamp
                duration_text = format_duration(duration_seconds)
            
            # Live-Statistiken (Felder) löschen und Dauer in die Beschreibung packen
            embed["fields"] = []
            if duration_text:
                embed["description"] = f"Der Stream war für **{duration_text}** online."
            else:
                embed["description"] = "Der Stream wurde beendet."
            
            # Kanal-URL auslesen
            channel_url = embed.get("url", "https://twitch.tv")
            
            # NUR DER ARCHIV BUTTON
            payload = {
                "embeds": [embed],
                "components": [{
                    "type": 1, 
                    "components": [
                        {"type": 2, "style": 5, "label": "Vergangene Streams", "url": f"{channel_url}/videos"}
                    ]
                }] 
            }
            
            patch_response = requests.patch(message_url, headers=HEADERS, json=payload)
            if patch_response.status_code in [200, 201]:
                print(f"🔄 Nachricht {message_id} erfolgreich auf Offline aktualisiert.")
            else:
                print(f"❌ Fehler beim Aktualisieren der Nachricht {message_id}: {patch_response.text}")
        else:
            print(f"⚠️ Keine Embeds in der Nachricht {message_id} gefunden.")
    else:
        print(f"❌ Konnte Originalnachricht {message_id} nicht abrufen: {get_response.status_code}")

def main():
    if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID or not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
        print("❌ Fehler: Fehlende Umgebungsvariablen in den GitHub Secrets!")
        return

    config = load_json_file(CONFIG_FILE, [])
    state = load_json_file(STATE_FILE, {})
    state_changed = False

    if not os.path.exists(STATE_FILE):
        state_changed = True

    print(f"Rufe Daten für {len(config)} Streamer ab...")
    live_streams_data = fetch_twitch_data_batch(config)

    for streamer in config:
        streamer_id = streamer["id"]
        channel = streamer.get("channel", "").lower()
        
        if streamer_id not in state:
            state[streamer_id] = {"is_live": False, "message_id": None, "started_at": 0}
            state_changed = True

        current_state = state[streamer_id]
        
        is_live = channel in live_streams_data
        
        if is_live and not current_state.get("is_live"):
            stream_data = live_streams_data[channel]
            msg_id = send_live_notification(streamer, stream_data)
            
            # Status aktualisieren UND Startzeit speichern
            current_state["is_live"] = True
            current_state["message_id"] = msg_id
            current_state["started_at"] = stream_data.get("started_at", 0)
            state_changed = True

        elif not is_live and current_state.get("is_live"):
            # Offline-Nachricht updaten und Startzeit übergeben
            started_at = current_state.get("started_at", 0)
            update_offline_message(current_state["message_id"], started_at)
            
            # Status zurücksetzen
            current_state["is_live"] = False
            current_state["message_id"] = None
            current_state["started_at"] = 0
            state_changed = True

    if state_changed:
        save_state(state)

if __name__ == "__main__":
    main()
