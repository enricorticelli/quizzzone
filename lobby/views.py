import base64
from io import BytesIO

import qrcode
from django.utils import timezone
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .forms import ICON_CHOICES, ICON_EMOJIS, ICON_LABELS, JoinForm
from .models import Player, Room

MAX_PLAYERS = 10


def broadcast_room_state(room):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    players = list(room.players.all())
    host = players[0] if players else None
    data_players = [
        {
            "nickname": player.nickname,
            "icon": player.icon,
            "icon_display": f"{ICON_EMOJIS[player.icon]} {ICON_LABELS[player.icon]}",
            "is_host": host == player,
        }
        for player in players
    ]
    async_to_sync(channel_layer.group_send)(
        f"room_{room.code}",
        {
            "type": "room_update",
            "data": {
                "type": "room_state",
                "room": room.code,
                "players_count": len(players),
                "max_players": MAX_PLAYERS,
                "can_start": len(players) >= 2,
                "host": host.nickname if host else None,
                "host_is_me": False,
                "players": data_players,
                "started": room.started,
            },
        },
    )


def ensure_session(request):
    if not request.session.session_key:
        request.session.create()


def create_room(request):
    ensure_session(request)
    room = Room.objects.create()
    request.session["room_code"] = room.code
    return redirect("room", code=room.code)


def home_view(request):
    ensure_session(request)
    # Endpoint per l'host: crea sempre una nuova stanza e reindirizza alla lobby.
    room = Room.objects.create()
    request.session["room_code"] = room.code
    return redirect("room", code=room.code)


def join_lookup(request):
    ensure_session(request)
    session_key = request.session.session_key
    recent_player = (
        Player.objects.select_related("room")
        .filter(session_key=session_key)
        .order_by("-joined_at")
        .first()
    )
    recent_room = recent_player.room if recent_player else None

    code_error = None
    code_value = ""
    if request.method == "POST":
        code_value = request.POST.get("code", "").strip().upper()
        if not code_value:
            code_error = "Inserisci il codice stanza."
        elif not Room.objects.filter(code=code_value).exists():
            code_error = "Codice stanza non trovato."
        else:
            return redirect("join_room", code=code_value)

    return render(
        request,
        "lobby/home.html",
        {
            "code_error": code_error,
            "code_value": code_value,
            "recent_room": recent_room,
        },
    )


def room_view(request, code):
    ensure_session(request)
    room = get_object_or_404(Room, code=code)
    session_key = request.session.session_key
    existing_player = room.players.filter(session_key=session_key).first()
    if room.started:
        # Se la partita è avviata, manda i giocatori alla schermata di gioco e blocca nuovi ingressi.
        if existing_player:
            return redirect("game_view", code=room.code)
        return render(request, "lobby/join_closed.html", {"room": room})

    form = JoinForm(room=room)

    join_url = request.build_absolute_uri(reverse("join_room", args=[room.code])).replace("https://", "http://")
    entry_url = request.build_absolute_uri(reverse("join_lookup"))
    qr_data_url = build_qr_data_url(join_url)
    players = list(room.players.all())
    players_count = len(players)
    host = players[0] if players else None
    taken_icons = {player.icon for player in players}
    is_full = players_count >= MAX_PLAYERS
    available_icons = [value for value, _ in ICON_CHOICES if value not in taken_icons]

    selected_icon = form["icon"].value() if "icon" in form.fields else None
    can_start = players_count >= 2
    is_host = existing_player == host if existing_player else False

    if room.started and existing_player:
        return redirect("game_view", code=room.code)

    return render(
        request,
        "lobby/room.html",
        {
            "room": room,
            "players": players,
            "players_count": players_count,
            "current_player": existing_player,
            "qr_data_url": qr_data_url,
            "join_url": join_url,
            "is_full": is_full,
            "available_icons": available_icons,
            "icon_lookup": {value: f"{ICON_EMOJIS[value]} {ICON_LABELS[value]}" for value, _ in ICON_CHOICES},
            "icon_emoji": ICON_EMOJIS,
            "max_players": MAX_PLAYERS,
            "selected_icon": selected_icon,
            "host": host,
            "can_start": can_start,
            "is_host": is_host,
            # Relative URL evita mixed content dietro tunnel HTTPS.
            "state_url": reverse("room_state", args=[room.code]),
            "entry_url": entry_url,
            "start_url": reverse("start_game", args=[room.code]),
            "game_url": reverse("game_view", args=[room.code]),
        },
    )


def build_qr_data_url(join_url):
    qr_img = qrcode.make(join_url)
    buffer = BytesIO()
    qr_img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


@require_GET
def room_state(request, code):
    ensure_session(request)
    room = get_object_or_404(Room, code=code)
    players = list(room.players.all())
    host = players[0] if players else None
    players_count = len(players)
    can_start = players_count >= 2
    me_session = request.session.session_key

    host_is_me = host.session_key == me_session if host else False

    data_players = []
    for player in players:
        data_players.append(
            {
                "nickname": player.nickname,
                "icon": player.icon,
                "icon_display": f"{ICON_EMOJIS[player.icon]} {ICON_LABELS[player.icon]}",
                "is_host": host == player,
                "is_me": player.session_key == me_session,
            }
        )

    return JsonResponse(
        {
            "room": room.code,
            "players_count": players_count,
            "max_players": MAX_PLAYERS,
            "can_start": can_start,
            "started": room.started,
            "host": host.nickname if host else None,
            "host_is_me": host_is_me,
            "players": data_players,
        }
    )


def join_room(request, code):
    ensure_session(request)
    room = get_object_or_404(Room, code=code)
    session_key = request.session.session_key
    existing_player = room.players.filter(session_key=session_key).first()
    if room.started:
        if existing_player:
            return redirect("game_view", code=room.code)
        return render(request, "lobby/join_closed.html", {"room": room})
    players = list(room.players.all())
    host = players[0] if players else None
    entry_url = request.build_absolute_uri(reverse("join_lookup"))
    can_start = len(players) >= 2

    if request.method == "POST" and not existing_player:
        form = JoinForm(request.POST, room=room)
        if room.players.count() >= MAX_PLAYERS:
            form.add_error(None, "La stanza è piena (max 10 giocatori).")
        elif form.is_valid():
            try:
                Player.objects.create(
                    room=room,
                    nickname=form.cleaned_data["nickname"],
                    icon=form.cleaned_data["icon"],
                    session_key=session_key,
                )
                broadcast_room_state(room)
                return redirect("join_room", code=room.code)
            except IntegrityError:
                form.add_error(None, "Nickname o icona già in uso. Riprova.")
    else:
        form = JoinForm(room=room)

    players_count = len(players)
    taken_icons = {player.icon for player in players}
    is_full = players_count >= MAX_PLAYERS
    available_icons = [value for value, _ in ICON_CHOICES if value not in taken_icons]
    selected_icon = form["icon"].value() if "icon" in form.fields else None

    return render(
        request,
        "lobby/join.html",
        {
            "room": room,
            "players_count": players_count,
            "form": form,
            "current_player": existing_player,
            "is_full": is_full,
            "available_icons": available_icons,
            "icon_lookup": {value: f"{ICON_EMOJIS[value]} {ICON_LABELS[value]}" for value, _ in ICON_CHOICES},
            "icon_emoji": ICON_EMOJIS,
            "max_players": MAX_PLAYERS,
            "selected_icon": selected_icon,
            "host": host,
            # Relative URL evita mixed content dietro tunnel HTTPS.
            "state_url": reverse("room_state", args=[room.code]),
            "entry_url": entry_url,
            "can_start": can_start,
            "leave_url": reverse("leave_room", args=[room.code]),
            "start_url": reverse("start_game", args=[room.code]),
            "game_url": reverse("game_view", args=[room.code]),
        },
    )


@require_POST
def leave_room(request, code):
    ensure_session(request)
    room = get_object_or_404(Room, code=code)
    session_key = request.session.session_key
    room.players.filter(session_key=session_key).delete()
    broadcast_room_state(room)
    return redirect("join_room", code=room.code)


@require_POST
def start_game(request, code):
    ensure_session(request)
    room = get_object_or_404(Room, code=code)
    session_key = request.session.session_key
    host = room.players.order_by("joined_at").first()
    if not host or host.session_key != session_key:
        return redirect("room", code=room.code)
    room.started = True
    room.started_at = timezone.now()
    room.save(update_fields=["started", "started_at"])
    broadcast_room_state(room)
    return redirect("game_view", code=room.code)


def game_view(request, code):
    ensure_session(request)
    room = get_object_or_404(Room, code=code)
    if not room.started:
        return redirect("room", code=room.code)
    return render(request, "lobby/game.html", {"room": room})
