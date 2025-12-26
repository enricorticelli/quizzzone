from django.urls import path

from . import ws_consumers

websocket_urlpatterns = [
    path("ws/stanza/<str:code>/", ws_consumers.RoomConsumer.as_asgi()),
]
