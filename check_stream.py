import os
import json
import requests
import time

CONFIG_FILE = "config.json"
STATE_FILE = "state.json"

# Environment Variables mapping from GitHub Secrets
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
    with open(filepath, "r") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

def get_twitch_access_token():
    url = f"https://id.twitch.tv/oauth2/token?client_id={TWITCH_CLIENT_ID}&client_secret={TWITCH_CLIENT_SECRET}&grant_type=client_credentials"
    response = requests.post(url)
    if response.status_code == 200:
        return response.json().get("access_token")
    print("❌ Failed to get Twitch Access Token")
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
    
    # 1. Fetch live streams (Batched request)
    params = [("user_login", login) for login in logins]
    streams_resp = requests.get("https://api.twitch.tv/helix/streams", headers=twitch_headers, params=params)
    live_streams = streams_resp.json().get("data", [])
    
    if not live_streams:
        return {} # No one is live
        
    # 2. Fetch User Profiles for Avatars
    live_logins = [s["user_login"] for s in live_streams]
    users_params = [("login", login) for login in live_logins]
    users_resp = requests.get("https://api.twitch.tv/helix/users", headers=twitch_headers, params=users_params)
    users_data = users_resp.json().get("data", [])
    
    user_info = {u["login"]: {"avatar": u["profile_image_url"], "id": u["id"]} for u in users_data}
    
    live_data_map = {}
    
    for stream in live_streams:
        login = stream["user_login"].lower()
        broadcaster_id = user_info.get(login, {}).get("id", "")
        avatar_url = user_info.get(login, {}).get("avatar", "")
        
        followers_count = "N/A"
        # 3. Fetch Follower count
        if broadcaster_id:
            followers_resp = requests.get(f"https://api.twitch.tv/helix/channels/followers?broadcaster_id={broadcaster_id}", headers=twitch_headers)
            if followers_resp.status_code == 200:
                followers_count = str(followers_resp.json().get("total", "N/A"))
        
        thumb_url = stream["thumbnail_url"].replace("{width}", "1920").replace("{height}", "1080")
        thumb_url += f"?t={int(time.time())}"
        
        live_data_map[login] = {
            "is_streaming": True,
            "title": stream["title"],
            "game_name": stream["game_name"],
            "url": f"https://twitch.tv/{login}",
            "thumbnail_url": thumb_url,
            "avatar_url": avatar_url,
            "followers": followers_count
        }
        
    return live_data_map

def send_live_notification(streamer_config, stream_data):
    title = stream_data.get("title", "Live Stream!")
    url = stream_data.get("url", "https://twitch.tv")
    game = stream_data.get("game_name", "Just Chatting")
    thumbnail = stream_data.get("thumbnail_url", "")
    avatar = stream_data.get("avatar_url", "")
    followers = stream_data.get("followers", "N/A")
    
    channel_name = streamer_config.get("channel", "Twitch").title()

    content_parts = []
    if streamer_config.get("ping_role") and streamer_config.get("role_id"):
        content_parts.append(f"<@&{streamer_config['role_id']}>")
        
    custom_text = streamer_config.get("custom_text", "")
    if custom_text:
        content_parts.append(custom_text)
        
    final_content = " ".join(content_parts)

    payload = {
        "content": final_content,
        "embeds": [{
            "author": {
                "name": f"{channel_name} is LIVE!",
                "url": url,
                "icon_url": avatar
            },
            "description": f"**[{title}]({url})**",
            "color": 9520895, 
            "fields": [
                {"name": "Kategorie", "value": game, "inline": True},
                {"name": "Follower", "value": followers, "inline": True}
            ],
            "image": {"url": thumbnail} if thumbnail else {},
        }],
        "components": [{
            "type": 1, 
            "components": [
                {"type": 2, "style": 5, "label": "Live zuschauen", "url": url},
                {"type": 2, "style": 5, "label": "Vergangene Streams", "url": f"{url}/videos"},
                {"type": 2, "style": 5, "label": "Streamer Abonnieren", "url": f"https://subs.twitch.tv/{streamer_config.get('channel')}"}
            ]
        }]
    }

    response = requests.post(BASE_API_URL, headers=HEADERS, json=payload)
    if response.status_code in [200, 201]:
        print(f"✅ Live notification sent for {streamer_config['id']}")
        return response.json().get("id")
    else:
        print(f"❌ Failed to send Discord notification: {response.status_code} - {response.text}")
        return None

def update_offline_message(message_id):
    if not message_id: return

    edit_url = f"{BASE_API_URL}/{message_id}"
    payload = {
        "content": "",
        "embeds": [{
            "title": "💤 Stream Beendet",
            "description": "Thanks for watching! Catch you next time.",
            "color": 8421504,
        }],
        "components": [] 
    }
    requests.patch(edit_url, headers=HEADERS, json=payload)
    print(f"🔄 Message {message_id} updated to Offline status.")

def main():
    if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID or not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
        print("❌ Error: Missing Environment Variables in GitHub Secrets!")
        return

    config = load_json_file(CONFIG_FILE, [])
    state = load_json_file(STATE_FILE, {})
    state_changed = False

    if not os.path.exists(STATE_FILE):
        state_changed = True

    print(f"Fetching data for {len(config)} streamers...")
    live_streams_data = fetch_twitch_data_batch(config)

    for streamer in config:
        streamer_id = streamer["id"]
        channel = streamer.get("channel", "").lower()
        
        if streamer_id not in state:
            state[streamer_id] = {"is_live": False, "message_id": None}
            state_changed = True

        current_state = state[streamer_id]
        
        # Check if the channel exists in our "currently live" dictionary
        is_live = channel in live_streams_data
        
        if is_live and not current_state["is_live"]:
            stream_data = live_streams_data[channel]
            msg_id = send_live_notification(streamer, stream_data)
            current_state["is_live"] = True
            current_state["message_id"] = msg_id
            state_changed = True

        elif not is_live and current_state["is_live"]:
            update_offline_message(current_state["message_id"])
            current_state["is_live"] = False
            current_state["message_id"] = None
            state_changed = True

    if state_changed:
        save_state(state)

if __name__ == "__main__":
    main()
