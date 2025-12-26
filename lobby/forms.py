from django import forms

ICON_SET = [
    ("volpe", "🦊", "Volpe"),
    ("gatto", "🐱", "Gatto"),
    ("cane", "🐶", "Cane"),
    ("gufo", "🦉", "Gufo"),
    ("panda", "🐼", "Panda"),
    ("lama", "🦙", "Lama"),
    ("robot", "🤖", "Robot"),
    ("delfino", "🐬", "Delfino"),
    ("fenice", "🐦", "Fenice"),
    ("drago", "🐉", "Drago"),
    ("ninja", "🥷", "Ninja"),
    ("razzo", "🚀", "Razzo"),
]

ICON_CHOICES = [(value, label) for value, _, label in ICON_SET]
ICON_EMOJIS = {value: emoji for value, emoji, _ in ICON_SET}
ICON_LABELS = {value: label for value, _, label in ICON_SET}


class JoinForm(forms.Form):
    nickname = forms.CharField(
        label="Nickname",
        max_length=20,
        widget=forms.TextInput(attrs={"placeholder": "Scegli il tuo nome"}),
    )
    icon = forms.ChoiceField(
        label="Icona",
        choices=ICON_CHOICES,
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, room=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.room = room

    def clean_nickname(self):
        nickname = self.cleaned_data["nickname"].strip()
        if not nickname:
            raise forms.ValidationError("Scegli un nickname.")
        if self.room and self.room.players.filter(nickname__iexact=nickname).exists():
            raise forms.ValidationError("Questo nickname è già in uso nella stanza.")
        return nickname

    def clean_icon(self):
        icon = self.cleaned_data["icon"]
        if self.room and self.room.players.filter(icon=icon).exists():
            raise forms.ValidationError("Questa icona è già stata scelta.")
        return icon
