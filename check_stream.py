import os
import json
import requests
import time

CONFIG_FILE = "config.json"
STATE_FILE = "state.json"

BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID")

BASE_API_URL = f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"

HEADERS = {
    "Authorization": f"Bot {BOT_TOKEN}",
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

def fetch_twitch_data(streamer):
    channel = streamer.get("channel", "")
    if not channel:
        return None

    try:
        uptime = requests.get(f"https://decapi.me/twitch/uptime/{channel}", timeout=10).text

        print(f"🕵️ Debug [{channel}]: DecAPI returned -> {uptime}")
        if "Channel is not live" in uptime or "offline" in uptime.lower():
            return {"is_streaming": False}
        
        title = requests.get(f"https://decapi.me/twitch/title/{channel}", timeout=10).text
        game = requests.get(f"https://decapi.me/twitch/game/{channel}", timeout=10).text
        
        channel_lower = channel.lower()
        # The ?t= timestamp forces Discord to grab a fresh thumbnail every time
        thumbnail = f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{channel_lower}-1920x1080.jpg?t={int(time.time())}"
        
        return {
            "is_streaming": True,
            "title": title,
            "game_name": game,
            "url": f"https://twitch.tv/{channel}",
            "thumbnail_url": thumbnail
        }
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Error fetching Twitch data for {channel}: {e}")
        return None

def send_live_notification(streamer_config, stream_data):
    title = stream_data.get("title", "Live Stream!")
    url = stream_data.get("url", "https://twitch.tv")
    game = stream_data.get("game_name", "Just Chatting")
    thumbnail = stream_data.get("thumbnail_url", "")

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
            "title": "🚨 Stream is LIVE!",
            "description": f"**{title}**\n\n**Playing:** {game}",
            "color": 9520895, # Twitch Purple
            "image": {"url": thumbnail} if thumbnail else {},
        }],
        "components": [{
            "type": 1, 
            "components": [{
                "type": 2, 
                "style": 5, 
                "label": "📺 Watch Live",
                "url": url
            }]
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
            "title": "💤 Stream Ended",
            "description": "Thanks for watching! Catch you next time.",
            "color": 8421504,
        }],
        "components": [] 
    }
    requests.patch(edit_url, headers=HEADERS, json=payload)
    print(f"🔄 Message {message_id} updated to Offline status.")

def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        print("❌ Error: DISCORD_BOT_TOKEN or DISCORD_CHANNEL_ID is missing!")
        return

    config = load_json_file(CONFIG_FILE, [])
    state = load_json_file(STATE_FILE, {})
    state_changed = False

    if not os.path.exists(STATE_FILE):
        state_changed = True

    for streamer in config:
        streamer_id = streamer["id"]
        print(f"Checking {streamer_id}...")
        
        if streamer_id not in state:
            state[streamer_id] = {"is_live": False, "message_id": None}
            state_changed = True

        current_state = state[streamer_id]
        stream_data = fetch_twitch_data(streamer)
        
        if not stream_data:
            continue

        is_live = stream_data.get("is_streaming", False)

        if is_live and not current_state["is_live"]:
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
