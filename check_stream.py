import os
import json
import requests

CONFIG_FILE = "config.json"
STATE_FILE = "state.json"

# Append ?wait=true to ensure Discord returns the message ID so we can edit it later
WEBHOOK_URL = os.environ.get("CHANNEL_WEBHOOK_URL")
if WEBHOOK_URL and not WEBHOOK_URL.endswith("?wait=true"):
    WEBHOOK_URL += "?wait=true"

def load_json_file(filepath, default_value):
    """Utility to safely load a JSON file."""
    if not os.path.exists(filepath):
        return default_value
    with open(filepath, "r") as f:
        return json.load(f)

def save_state(state):
    """Saves the current tracker state."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

def fetch_stream_data(api_url):
    """Fetches stream data with error handling."""
    try:
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Error fetching {api_url}: {e}")
        return None

def send_live_notification(streamer_config, stream_data):
    """Sends the rich embed with buttons, optional role ping, and custom text."""
    title = stream_data.get("title", "Live Stream!")
    url = stream_data.get("url", "https://twitch.tv")
    game = stream_data.get("game_name", "Just Chatting")
    thumbnail = stream_data.get("thumbnail_url", "")

    # Build the plain-text content (Role Ping + Custom Text)
    content_parts = []
    
    if streamer_config.get("ping_role") and streamer_config.get("role_id"):
        content_parts.append(f"<@&{streamer_config['role_id']}>")
        
    custom_text = streamer_config.get("custom_text", "")
    if custom_text:
        content_parts.append(custom_text)
        
    final_content = " ".join(content_parts)

    payload = {
        "content": final_content,
        "username": "Stream Monitor",
        "embeds": [{
            "title": "🚨 Stream is LIVE!",
            "description": f"**{title}**\nPlaying: {game}",
            "color": 16711680, # Red
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

    response = requests.post(WEBHOOK_URL, json=payload)
    if response.status_code in [200, 201]:
        print(f"✅ Live notification sent for {streamer_config['id']}")
        return response.json().get("id") # Return the Discord Message ID
    else:
        print(f"❌ Failed to send Discord notification: {response.status_code}")
        return None

def update_offline_message(message_id):
    """Edits the previous live message to show the stream has ended."""
    if not message_id: return

    edit_url = f"{WEBHOOK_URL.split('?')[0]}/messages/{message_id}"
    
    payload = {
        "content": "", # Remove the role ping and custom text
        "embeds": [{
            "title": "💤 Stream Ended",
            "description": "Thanks for watching! Catch you next time.",
            "color": 8421504, # Gray
        }],
        "components": [] # Remove the watch button
    }

    requests.patch(edit_url, json=payload)
    print(f"🔄 Message {message_id} updated to Offline status.")

def main():
    if not WEBHOOK_URL:
        print("❌ Error: CHANNEL_WEBHOOK_URL secret is missing!")
        return

    config = load_json_file(CONFIG_FILE, [])
    state = load_json_file(STATE_FILE, {})
    state_changed = False

    # Ensure state file is created on the very first run even if nobody is live
    if not os.path.exists(STATE_FILE):
        state_changed = True

    for streamer in config:
        streamer_id = streamer["id"]
        print(f"Checking {streamer_id}...")
        
        # Ensure streamer exists in state
        if streamer_id not in state:
            state[streamer_id] = {"is_live": False, "message_id": None}
            state_changed = True

        current_state = state[streamer_id]
        stream_data = fetch_stream_data(streamer["api_url"])
        
        if not stream_data:
            continue

        is_live = stream_data.get("is_streaming", False)

        # Logic: Stream JUST went live
        if is_live and not current_state["is_live"]:
            msg_id = send_live_notification(streamer, stream_data)
            current_state["is_live"] = True
            current_state["message_id"] = msg_id
            state_changed = True

        # Logic: Stream JUST went offline
        elif not is_live and current_state["is_live"]:
            update_offline_message(current_state["message_id"])
            current_state["is_live"] = False
            current_state["message_id"] = None
            state_changed = True

    # Only write to file if something changed
    if state_changed:
        save_state(state)

if __name__ == "__main__":
    main()
