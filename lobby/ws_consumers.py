import json

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.urls import reverse

from .forms import ICON_EMOJIS, ICON_LABELS
from .models import Room
from .views import MAX_PLAYERS, build_game_state


class RoomConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.code = self.scope["url_route"]["kwargs"]["code"]
        self.group_name = f"room_{self.code}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_room_state()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        # Support manual ping from client.
        if text_data == "ping":
            await self.send_room_state()

    async def send_room_state(self):
        room = await self.get_room_or_none(self.code)
        if not room:
            await self.send(text_data=json.dumps({"type": "not_found"}))
            return
        players = await self.get_players(room)
        host = players[0] if players else None
        me_session = await self.get_session_key()
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
        payload = {
            "type": "room_state",
            "room": room.code,
            "players_count": len(players),
            "max_players": MAX_PLAYERS,
            "can_start": len(players) >= 2,
            "host": host.nickname if host else None,
            "host_is_me": bool(host and host.session_key == me_session),
            "players": data_players,
            "join_url": reverse("join_room", args=[room.code]),
            "started": room.started,
        }
        await self.send(text_data=json.dumps(payload))

    async def room_update(self, event):
        # On any broadcast, send a fresh state per connection (per-session flags).
        await self.send_room_state()

    async def game_update(self, event):
        # Ignore game updates in the lobby socket.
        return

    @database_sync_to_async
    def get_room_or_none(self, code):
        try:
            return Room.objects.get(code=code)
        except Room.DoesNotExist:
            return None

    @database_sync_to_async
    def get_players(self, room):
        return list(room.players.all())

    @sync_to_async
    def get_session_key(self):
        session = self.scope.get("session")
        return session.session_key if session else None


class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.code = self.scope["url_route"]["kwargs"]["code"]
        self.group_name = f"room_{self.code}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_game_state()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if text_data == "ping":
            await self.send_game_state()

    async def room_update(self, event):
        await self.send_game_state()

    async def game_update(self, event):
        await self.send_game_state()

    async def send_game_state(self):
        room = await self.get_room_or_none(self.code)
        if not room:
            await self.send(text_data=json.dumps({"type": "not_found"}))
            return
        session_key = await self.get_session_key()
        data = await sync_to_async(build_game_state)(room, session_key=session_key)
        await self.send(text_data=json.dumps(data))

    @database_sync_to_async
    def get_room_or_none(self, code):
        try:
            return Room.objects.select_related("game").get(code=code)
        except Room.DoesNotExist:
            return None

    @sync_to_async
    def get_session_key(self):
        session = self.scope.get("session")
        return session.session_key if session else None
