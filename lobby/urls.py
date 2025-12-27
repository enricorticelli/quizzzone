from django.urls import path

from . import views

urlpatterns = [
    path("", views.home_view, name="home"),
    path("entra/", views.join_lookup, name="join_lookup"),
    path("crea/", views.create_room, name="create_room"),
    path("stanza/<str:code>/", views.room_view, name="room"),
    path("stanza/<str:code>/entra/", views.join_room, name="join_room"),
    path("stanza/<str:code>/esci/", views.leave_room, name="leave_room"),
    path("stanza/<str:code>/start/", views.start_game, name="start_game"),
    path("stanza/<str:code>/gioco/", views.game_view, name="game_view"),
    path("stanza/<str:code>/state/", views.room_state, name="room_state"),
    path("stanza/<str:code>/gioco/state/", views.game_state, name="game_state"),
    path("stanza/<str:code>/gioco/scegli/", views.choose_question, name="choose_question"),
    path("stanza/<str:code>/gioco/rispondi/", views.submit_answer, name="submit_answer"),
]
