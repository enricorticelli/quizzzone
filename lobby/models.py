from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.translation import gettext_lazy as _


def generate_room_code():
    # 6-character uppercase code; regenerate if collision occurs.
    return get_random_string(6, allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


class Room(models.Model):
    code = models.CharField(max_length=8, unique=True, default=generate_room_code, editable=False)
    created_at = models.DateTimeField(default=timezone.now)
    started = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Stanza {self.code}"


class Player(models.Model):
    room = models.ForeignKey(Room, related_name="players", on_delete=models.CASCADE)
    nickname = models.CharField(max_length=20)
    icon = models.CharField(max_length=20)
    session_key = models.CharField(max_length=40)
    joined_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [
            ("room", "nickname"),
            ("room", "icon"),
        ]
        ordering = ["joined_at"]

    def __str__(self):
        return f"{self.nickname} ({self.room.code})"


class Question(models.Model):
    CATEGORY_STORIA = "storia"
    CATEGORY_SCIENZA = "scienza"
    CATEGORY_CULTURA = "cultura"
    CATEGORY_SPORT = "sport"
    CATEGORY_GEOGRAFIA = "geografia"

    CATEGORY_CHOICES = [
        (CATEGORY_STORIA, "Storia"),
        (CATEGORY_SCIENZA, "Scienza"),
        (CATEGORY_CULTURA, "Cultura generale"),
        (CATEGORY_SPORT, "Sport"),
        (CATEGORY_GEOGRAFIA, "Geografia"),
    ]

    LEVEL_CHOICES = [(level, f"Livello {level}") for level in range(1, 6)]

    OPTION_A = "A"
    OPTION_B = "B"
    OPTION_C = "C"
    OPTION_CHOICES = [
        (OPTION_A, "Opzione A"),
        (OPTION_B, "Opzione B"),
        (OPTION_C, "Opzione C"),
    ]

    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    difficulty = models.PositiveSmallIntegerField(choices=LEVEL_CHOICES)
    text = models.TextField(verbose_name="Domanda")
    option_a = models.CharField(max_length=255, verbose_name="Opzione A")
    option_b = models.CharField(max_length=255, verbose_name="Opzione B")
    option_c = models.CharField(max_length=255, verbose_name="Opzione C")
    correct_option = models.CharField(max_length=1, choices=OPTION_CHOICES)
    is_active = models.BooleanField(default=True, help_text="Disattiva per escludere la domanda dai quiz.")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["category", "difficulty", "created_at"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(difficulty__gte=1, difficulty__lte=5),
                name="question_level_between_1_5",
            ),
        ]

    def __str__(self):
        return f"[{self.get_category_display()} {self.difficulty}] {self.text[:50]}"

    @property
    def points(self):
        return self.difficulty

    def get_options(self):
        return {
            self.OPTION_A: self.option_a,
            self.OPTION_B: self.option_b,
            self.OPTION_C: self.option_c,
        }


class Game(models.Model):
    STATE_CHOOSING = "choosing"
    STATE_ANSWERING = "answering"
    STATE_FINISHED = "finished"
    STATE_CHOICES = [
        (STATE_CHOOSING, _("Scelta categoria/livello")),
        (STATE_ANSWERING, _("Domanda attiva")),
        (STATE_FINISHED, _("Finita")),
    ]

    room = models.OneToOneField(Room, related_name="game", on_delete=models.CASCADE)
    current_player = models.ForeignKey(
        Player, related_name="current_games", on_delete=models.SET_NULL, null=True, blank=True
    )
    current_turn = models.OneToOneField(
        "GameTurn", related_name="current_in_game", on_delete=models.SET_NULL, null=True, blank=True
    )
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default=STATE_CHOOSING)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Partita {self.room.code}"

    def rotate_to_next_player(self, only_on_wrong=False, was_correct=None):
        """Passa al giocatore successivo mantenendo l'ordine di ingresso."""
        if self.current_player is None:
            return None
        if only_on_wrong and was_correct:
            return self.current_player
        players = list(self.players.order_by("order"))
        if not players:
            return None
        current_idx = next((idx for idx, gp in enumerate(players) if gp.player_id == self.current_player_id), 0)
        next_idx = (current_idx + 1) % len(players)
        next_player = players[next_idx].player
        self.current_player = next_player
        self.save(update_fields=["current_player"])
        return next_player

    @property
    def is_over(self):
        return self.state == self.STATE_FINISHED


class GameQuestion(models.Model):
    game = models.ForeignKey(Game, related_name="game_questions", on_delete=models.CASCADE)
    question = models.ForeignKey(Question, related_name="game_questions", on_delete=models.CASCADE)

    class Meta:
        unique_together = [("game", "question")]

    def __str__(self):
        return f"{self.question} -> {self.game}"


class GamePlayer(models.Model):
    game = models.ForeignKey(Game, related_name="players", on_delete=models.CASCADE)
    player = models.ForeignKey(Player, related_name="game_entries", on_delete=models.CASCADE)
    order = models.PositiveIntegerField()
    score = models.IntegerField(default=0)

    class Meta:
        unique_together = [("game", "player")]
        ordering = ["order"]

    def __str__(self):
        return f"{self.player.nickname} ({self.score} pt)"


class GameTurn(models.Model):
    game = models.ForeignKey(Game, related_name="turns", on_delete=models.CASCADE)
    player = models.ForeignKey(Player, related_name="turns", on_delete=models.CASCADE)
    question = models.ForeignKey(Question, related_name="turns", on_delete=models.CASCADE)
    started_at = models.DateTimeField(default=timezone.now)
    answered_at = models.DateTimeField(null=True, blank=True)
    selected_option = models.CharField(max_length=1, choices=Question.OPTION_CHOICES, null=True, blank=True)
    was_correct = models.BooleanField(null=True, blank=True)
    points_awarded = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["game", "question"], name="unique_question_per_game"),
        ]
        ordering = ["-started_at"]

    def __str__(self):
        return f"Turno {self.id} ({self.game.room.code})"
