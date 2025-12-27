import csv
import io

from django import forms
from django.contrib import admin, messages
from django.template.response import TemplateResponse
from django.urls import path

from .models import Game, GamePlayer, GameQuestion, GameTurn, Player, Question, Room


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("text_short", "category", "difficulty", "is_active")
    list_filter = ("category", "difficulty", "is_active")
    search_fields = ("text", "option_a", "option_b", "option_c")
    change_list_template = "admin/lobby/question/change_list.html"
    fieldsets = (
        ("Dettagli domanda", {"fields": ("category", "difficulty", "text", "is_active")}),
        ("Risposte", {"fields": ("option_a", "option_b", "option_c", "correct_option")}),
    )

    def text_short(self, obj):
        return obj.text[:70]

    text_short.short_description = "Domanda"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("import/", self.admin_site.admin_view(self.import_csv), name="lobby_question_import"),
        ]
        return custom_urls + urls

    def import_csv(self, request):
        if request.method == "POST":
            form = QuestionImportForm(request.POST, request.FILES)
            if form.is_valid():
                uploaded = form.cleaned_data["file"]
                try:
                    created, errors = import_questions_from_csv(uploaded)
                    if created:
                        messages.success(request, f"{created} domande create.")
                    if errors:
                        messages.warning(request, f"Import parziale: {errors}")
                except ValueError as exc:
                    messages.error(request, str(exc))
                return self.changelist_view(request)
        else:
            form = QuestionImportForm()

        context = self.admin_site.each_context(request)
        context.update({"opts": self.model._meta, "form": form})
        return TemplateResponse(request, "admin/lobby/question/import_form.html", context)


class GamePlayerInline(admin.TabularInline):
    model = GamePlayer
    extra = 0
    readonly_fields = ("player", "score", "order")


class GameTurnInline(admin.TabularInline):
    model = GameTurn
    extra = 0
    readonly_fields = (
        "player",
        "question",
        "started_at",
        "answered_at",
        "selected_option",
        "was_correct",
        "points_awarded",
    )


class GameQuestionInline(admin.TabularInline):
    model = GameQuestion
    extra = 0
    readonly_fields = ("question",)


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("room", "state", "current_player", "started_at", "finished_at")
    readonly_fields = ("room", "started_at", "finished_at")
    inlines = [GamePlayerInline, GameQuestionInline, GameTurnInline]


admin.site.register(Room)
admin.site.register(Player)


class QuestionImportForm(forms.Form):
    file = forms.FileField(label="File CSV (UTF-8)")


def import_questions_from_csv(uploaded_file):
    try:
        wrapper = io.TextIOWrapper(uploaded_file, encoding="utf-8")
    except Exception as exc:
        raise ValueError(f"Impossibile leggere il file: {exc}") from exc

    reader = csv.DictReader(wrapper)
    required_headers = {"category", "difficulty", "text", "option_a", "option_b", "option_c", "correct_option"}
    if set(reader.fieldnames or []) < required_headers:
        raise ValueError(f"Intestazioni mancanti, attese: {', '.join(sorted(required_headers))}")

    valid_categories = {key for key, _ in Question.CATEGORY_CHOICES}
    valid_options = {opt for opt, _ in Question.OPTION_CHOICES}
    created = 0
    errors = []

    for idx, row in enumerate(reader, start=2):  # start=2 to account for header
        category = (row.get("category") or "").strip().lower()
        try:
            difficulty = int(row.get("difficulty"))
        except (TypeError, ValueError):
            errors.append(f"riga {idx}: difficoltà non valida")
            continue
        text = (row.get("text") or "").strip()
        option_a = (row.get("option_a") or "").strip()
        option_b = (row.get("option_b") or "").strip()
        option_c = (row.get("option_c") or "").strip()
        correct_option = (row.get("correct_option") or "").strip().upper()
        is_active_val = (row.get("is_active") or "true").strip().lower() in ("1", "true", "yes", "y")

        if category not in valid_categories:
            errors.append(f"riga {idx}: categoria '{category}' non valida")
            continue
        if difficulty not in range(1, 6):
            errors.append(f"riga {idx}: difficoltà fuori range 1-5")
            continue
        if correct_option not in valid_options:
            errors.append(f"riga {idx}: risposta corretta deve essere A/B/C")
            continue
        if not text or not option_a or not option_b or not option_c:
            errors.append(f"riga {idx}: testo o opzioni mancanti")
            continue

        Question.objects.create(
            category=category,
            difficulty=difficulty,
            text=text,
            option_a=option_a,
            option_b=option_b,
            option_c=option_c,
            correct_option=correct_option,
            is_active=is_active_val,
        )
        created += 1

    return created, "; ".join(errors)
