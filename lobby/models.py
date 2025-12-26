from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string


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
