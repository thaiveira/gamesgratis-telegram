import html
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests


BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")  # @nomedocanal ou -100xxxxxxxxxx

# Filtro opcional de lojas, separadas por vírgula. Ex.: "steam,epic-games-store,gog"
# Vazio = todas as lojas.
PLATFORMS = [p.strip() for p in os.environ.get("PLATFORMS", "").split(",") if p.strip()]

FIRST_RUN_LIMIT = int(os.environ.get("FIRST_RUN_LIMIT", "5"))

DRY_RUN = os.environ.get("DRY_RUN") == "1"

STATE_FILE = Path(__file__).parent / "sent.json"
API_URL = "https://www.gamerpower.com/api/giveaways"
TG_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def load_state():
    """Retorna (ids_enviados, primeira_execucao)."""
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text())), False
    return set(), True


def save_state(ids):
 
    recent = sorted(ids)[-500:]
    STATE_FILE.write_text(json.dumps(recent))


def fetch_giveaways():
    resp = requests.get(API_URL, params={"type": "game", "sort-by": "date"}, timeout=30)
    if resp.status_code == 201 or not resp.text.strip():
        return []  
    resp.raise_for_status()
    games = resp.json()

    active = [g for g in games if g.get("status") == "Active"]
    if PLATFORMS:
        def match(g):
            plats = g.get("platforms", "").lower().replace(" ", "-")
            return any(p in plats for p in PLATFORMS)
        active = [g for g in active if match(g)]

  
    return sorted(active, key=lambda g: g["id"])


def format_end_date(raw):
    if not raw or raw == "N/A":
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y")
    except ValueError:
        return raw


def build_caption(g):
    title = html.escape(g["title"])
    worth = g.get("worth", "N/A")
    platforms = html.escape(g.get("platforms", ""))
    end = format_end_date(g.get("end_date"))

    lines = [f"🎮 <b>{title}</b>", ""]
    if worth and worth != "N/A":
        lines.append(f"💰 <s>{html.escape(worth)}</s> → <b>GRÁTIS</b>")
    else:
        lines.append("💰 <b>GRÁTIS</b>")
    lines.append(f"🖥 {platforms}")
    if end:
        lines.append(f"⏳ Até {end}")

    caption = "\n".join(lines)
    return caption[:1024] 


def send_game(g):
    caption = build_caption(g)
    keyboard = {
        "inline_keyboard": [[{"text": "🎁 Resgatar", "url": g["open_giveaway_url"]}]]
    }

    if DRY_RUN:
        print("-" * 40)
        print(caption)
        print("->", g["open_giveaway_url"])
        return

    payload = {
        "chat_id": CHAT_ID,
        "caption": caption,
        "parse_mode": "HTML",
        "reply_markup": json.dumps(keyboard),
    }
    photo = g.get("image") or g.get("thumbnail")
    if photo:
        r = requests.post(f"{TG_URL}/sendPhoto", data={**payload, "photo": photo}, timeout=30)
        if r.ok:
            return
        print(f"  sendPhoto falhou ({r.status_code}), tentando só texto...")

    text_payload = {k: v for k, v in payload.items() if k != "caption"}
    text_payload["text"] = caption
    r = requests.post(f"{TG_URL}/sendMessage", data=text_payload, timeout=30)
    r.raise_for_status()


def main():
    if not DRY_RUN and (not BOT_TOKEN or not CHAT_ID):
        sys.exit("Defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID (ou use DRY_RUN=1).")

    sent, first_run = load_state()
    giveaways = fetch_giveaways()
    new = [g for g in giveaways if g["id"] not in sent]

    if first_run and len(new) > FIRST_RUN_LIMIT:
        sent.update(g["id"] for g in new[:-FIRST_RUN_LIMIT])
        new = new[-FIRST_RUN_LIMIT:]

    print(f"{len(giveaways)} ativos, {len(new)} novos.")

    for g in new:
        try:
            send_game(g)
            sent.add(g["id"])
            print(f"  enviado: {g['title']}")
            time.sleep(3) 
        except requests.RequestException as e:
            print(f"  erro ao enviar {g['title']}: {e}")

    if not DRY_RUN:
        save_state(sent)


if __name__ == "__main__":
    main()
