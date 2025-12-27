import base64
import random
from io import BytesIO

import qrcode
from django.utils import timezone
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import IntegrityError, transaction
from django.db.models import Count, F
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .forms import ICON_CHOICES, ICON_EMOJIS, ICON_LABELS, JoinForm
from .models import Game, GamePlayer, GameQuestion, GameTurn, Player, Question, Room

MAX_PLAYERS = 10
REQUIRED_COMBINATIONS = [(category, level) for category, _ in Question.CATEGORY_CHOICES for level in range(1, 6)]
QUESTIONS_PER_GAME = len(REQUIRED_COMBINATIONS)


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


def broadcast_game_state(room):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        f"room_{room.code}",
        {
            "type": "game_update",
            "data": build_game_state(room),
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
    if room.started:
        return redirect("game_view", code=room.code)
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
    if room.started:
        return redirect("game_view", code=room.code)

    players = list(room.players.order_by("joined_at"))
    if len(players) < 2:
        return redirect("room", code=room.code)
    first_player = random.choice(players)

    chosen_ids = []
    missing_slots = []
    for category, level in REQUIRED_COMBINATIONS:
        qid = (
            Question.objects.filter(is_active=True, category=category, difficulty=level)
            .order_by("?")
            .values_list("id", flat=True)
            .first()
        )
        if qid:
            chosen_ids.append(qid)
        else:
            missing_slots.append(f"{dict(Question.CATEGORY_CHOICES)[category]} livello {level}")

    if missing_slots:
        missing_text = ", ".join(missing_slots)
        return HttpResponse(
            f"Mancano domande per: {missing_text}. Aggiungi almeno una domanda per ogni materia e livello (1-5).",
            status=400,
        )

    with transaction.atomic():
        Game.objects.filter(room=room).delete()
        game = Game.objects.create(room=room, current_player=first_player, state=Game.STATE_CHOOSING)
        for idx, player in enumerate(players):
            GamePlayer.objects.create(game=game, player=player, order=idx)
        questions = Question.objects.filter(id__in=chosen_ids)
        for q in questions:
            GameQuestion.objects.create(game=game, question=q)
        room.started = True
        room.started_at = timezone.now()
        room.save(update_fields=["started", "started_at"])

    broadcast_room_state(room)
    broadcast_game_state(room)
    return redirect("game_view", code=room.code)


def game_view(request, code):
    ensure_session(request)
    room = get_object_or_404(Room, code=code)
    if not room.started:
        return redirect("room", code=room.code)
    return render(
        request,
        "lobby/game.html",
        {
            "room": room,
            "state_url": reverse("game_state", args=[room.code]),
            "choose_url": reverse("choose_question", args=[room.code]),
            "answer_url": reverse("submit_answer", args=[room.code]),
        },
    )


@require_GET
def game_state(request, code):
    ensure_session(request)
    room = get_object_or_404(Room, code=code)
    return JsonResponse(build_game_state(room, session_key=request.session.session_key))


@require_POST
def choose_question(request, code):
    ensure_session(request)
    room = get_object_or_404(Room, code=code)
    game = get_object_or_404(Game, room=room)
    if game.state == Game.STATE_FINISHED:
        return JsonResponse({"error": "La partita è già terminata."}, status=400)
    current_player = game.current_player
    if not current_player or current_player.session_key != request.session.session_key:
        return JsonResponse({"error": "Non è il tuo turno."}, status=403)

    category = request.POST.get("category")
    difficulty = request.POST.get("difficulty")
    try:
        difficulty = int(difficulty)
    except (TypeError, ValueError):
        return JsonResponse({"error": "Livello non valido."}, status=400)

    if category not in dict(Question.CATEGORY_CHOICES):
        return JsonResponse({"error": "Materia non valida."}, status=400)
    if difficulty not in range(1, 6):
        return JsonResponse({"error": "Livello non valido."}, status=400)

    if game.state != Game.STATE_CHOOSING:
        return JsonResponse({"error": "C'è già una domanda attiva."}, status=400)

    with transaction.atomic():
        qs = (
            GameQuestion.objects.select_related("question")
            .filter(game=game, question__category=category, question__difficulty=difficulty)
            .exclude(question__turns__game=game)
            .order_by("?")
        )
        game_question = qs.first()
        question = game_question.question if game_question else None
        if not question:
            return JsonResponse({"error": "Nessuna domanda disponibile per questa materia/livello."}, status=400)
        turn = GameTurn.objects.create(game=game, player=current_player, question=question)
        game.current_turn = turn
        game.state = Game.STATE_ANSWERING
        game.save(update_fields=["current_turn", "state"])

    broadcast_game_state(room)
    return JsonResponse(build_game_state(room, session_key=request.session.session_key))


@require_POST
def submit_answer(request, code):
    ensure_session(request)
    room = get_object_or_404(Room, code=code)
    game = get_object_or_404(Game, room=room)
    session_key = request.session.session_key
    if game.state != Game.STATE_ANSWERING or not game.current_turn:
        return JsonResponse({"error": "Nessuna domanda attiva."}, status=400)
    if not game.current_player or game.current_player.session_key != session_key:
        return JsonResponse({"error": "Non puoi rispondere, non è il tuo turno."}, status=403)

    selected = request.POST.get("option")
    if selected not in dict(Question.OPTION_CHOICES):
        return JsonResponse({"error": "Opzione non valida."}, status=400)

    with transaction.atomic():
        turn = GameTurn.objects.select_for_update().get(pk=game.current_turn_id)
        if turn.selected_option:
            return JsonResponse({"error": "Hai già risposto a questa domanda."}, status=400)
        turn.selected_option = selected
        correct = selected == turn.question.correct_option
        turn.was_correct = correct
        turn.answered_at = timezone.now()
        points = turn.question.points if correct else 0
        turn.points_awarded = points
        turn.save(update_fields=["selected_option", "was_correct", "answered_at", "points_awarded"])

        if points:
            GamePlayer.objects.filter(game=game, player=turn.player).update(score=F("score") + points)

        remaining_questions = (
            GameQuestion.objects.filter(game=game)
            .exclude(question__turns__game=game)
            .exclude(question=turn.question)
            .count()
        )

        game.current_turn = None
        if remaining_questions <= 0:
            game.state = Game.STATE_FINISHED
            game.finished_at = timezone.now()
            game.save(update_fields=["state", "finished_at", "current_turn"])
        else:
            game.state = Game.STATE_CHOOSING
            game.save(update_fields=["state", "current_turn"])
            game.rotate_to_next_player(only_on_wrong=True, was_correct=correct)

    broadcast_game_state(room)
    return JsonResponse(build_game_state(room, session_key=session_key))


def build_game_state(room, session_key=None):
    payload = {
        "type": "game_state",
        "room": room.code,
        "status": "not_started",
        "scoreboard": [],
        "current_player": None,
        "current_turn_id": None,
        "question": None,
        "options": None,
        "actions": {"can_choose": False, "can_answer": False},
        "remaining_questions": 0,
        "asked_questions": 0,
        "available": {},
        "game_over": False,
        "question_grid": {},
        "last_answer": None,
    }
    game = getattr(room, "game", None)
    if not room.started or not game:
        return payload

    game_players = list(game.players.select_related("player").order_by("order"))
    scoreboard = []
    for gp in game_players:
        scoreboard.append(
            {
                "nickname": gp.player.nickname,
                "icon": gp.player.icon,
                "score": gp.score,
                "is_me": gp.player.session_key == session_key if session_key else False,
            }
        )
    payload["scoreboard"] = sorted(scoreboard, key=lambda s: (-s["score"], s["nickname"]))
    payload["asked_questions"] = game.turns.count()

    current_player = game.current_player
    if current_player:
        payload["current_player"] = {
            "nickname": current_player.nickname,
            "icon": current_player.icon,
            "is_me": current_player.session_key == session_key if session_key else False,
        }

    remaining_by_level = get_remaining_by_level(game)
    payload["available"] = remaining_by_level
    payload["remaining_questions"] = sum(
        count for cat_data in remaining_by_level.values() for count in cat_data.values()
    )
    payload["question_grid"] = build_question_grid(
        game, current_player=current_player, remaining_by_level=remaining_by_level
    )
    last_answer = get_last_answer(game)

    if game.state == Game.STATE_FINISHED or payload["remaining_questions"] == 0:
        payload["status"] = Game.STATE_FINISHED
        payload["game_over"] = True
        payload["last_answer"] = last_answer
        return payload

    payload["status"] = game.state
    payload["game_over"] = False

    turn = game.current_turn
    if turn:
        payload["current_turn_id"] = turn.id
        payload["question"] = {
            "id": turn.question_id,
            "category": turn.question.category,
            "category_label": turn.question.get_category_display(),
            "difficulty": turn.question.difficulty,
            "text": turn.question.text,
        }
        if current_player and current_player.session_key == session_key:
            payload["options"] = turn.question.get_options()

    is_my_turn = bool(current_player and current_player.session_key == session_key)
    payload["actions"] = {
        "can_choose": is_my_turn and game.state == Game.STATE_CHOOSING and payload["remaining_questions"] > 0,
        "can_answer": is_my_turn and game.state == Game.STATE_ANSWERING and not (turn and turn.selected_option),
    }
    payload["last_answer"] = last_answer

    return payload


def get_remaining_by_level(game):
    remaining = {key: {level: 0 for level in range(1, 6)} for key, _ in Question.CATEGORY_CHOICES}
    aggregates = (
        GameQuestion.objects.filter(game=game)
        .exclude(question__turns__game=game)
        .values("question__category", "question__difficulty")
        .annotate(count=Count("id"))
    )
    for item in aggregates:
        remaining[item["question__category"]][item["question__difficulty"]] = item["count"]
    return remaining


def build_question_grid(game, current_player=None, remaining_by_level=None):
    remaining = remaining_by_level or get_remaining_by_level(game)
    turns = list(game.turns.select_related("question", "player"))
    turn_lookup = {(turn.question.category, turn.question.difficulty): turn for turn in turns}
    current_turn = game.current_turn
    grid = {category: {} for category, _ in Question.CATEGORY_CHOICES}
    for category, _ in Question.CATEGORY_CHOICES:
        for level in range(1, 6):
            cell = {
                "category": category,
                "difficulty": level,
                "available": remaining.get(category, {}).get(level, 0),
                "status": "available",
            }
            combo = (category, level)
            if current_turn and current_turn.question.category == category and current_turn.question.difficulty == level:
                cell["status"] = "active"
                cell["turn_id"] = current_turn.id
                if current_turn.player:
                    cell["player"] = {
                        "nickname": current_turn.player.nickname,
                        "icon": current_turn.player.icon,
                        "is_me": current_player.session_key == current_turn.player.session_key
                        if current_player
                        else False,
                    }
                if current_turn.selected_option:
                    cell["selected_option"] = current_turn.selected_option
            elif combo in turn_lookup:
                turn = turn_lookup[combo]
                cell["status"] = "asked"
                cell["turn_id"] = turn.id
                cell["player"] = {
                    "nickname": turn.player.nickname,
                    "icon": turn.player.icon,
                    "is_me": current_player.session_key == turn.player.session_key if current_player else False,
                }
                cell["was_correct"] = turn.was_correct
                cell["selected_option"] = turn.selected_option
            grid[category][level] = cell
    return grid


def get_last_answer(game):
    last_turn = (
        game.turns.select_related("player", "question")
        .exclude(answered_at__isnull=True)
        .order_by("-answered_at", "-id")
        .first()
    )
    if not last_turn:
        return None
    options = last_turn.question.get_options()
    return {
        "id": last_turn.id,
        "player": {
            "nickname": last_turn.player.nickname,
            "icon": last_turn.player.icon,
        },
        "question": {
            "category": last_turn.question.category,
            "category_label": last_turn.question.get_category_display(),
            "difficulty": last_turn.question.difficulty,
            "text": last_turn.question.text,
        },
        "selected_option": last_turn.selected_option,
        "selected_option_label": options.get(last_turn.selected_option),
        "was_correct": last_turn.was_correct,
        "answered_at": last_turn.answered_at.isoformat() if last_turn.answered_at else None,
        "points": last_turn.points_awarded,
    }
