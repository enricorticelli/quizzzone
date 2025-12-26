# Quizzzone

Lobby web in Django per Quizzzone con join via codice/QR, nickname e icone unici (max 10 giocatori). UI in italiano.

## Requisiti
- Python 3.11+
- Docker + Docker Compose (consigliato) oppure un Postgres locale
- pip

## Avvio rapido con Docker
```bash
docker compose -f docker-compose.dev.yml up --build
```
Avvia Postgres + Django (migrate, collectstatic, Daphne) su http://localhost:8000. Il codice è montato in volume per autoreload.

## Avvio locale manuale (senza Docker)
1) Assicurati di avere un Postgres raggiungibile (host `localhost`, porta `5432`, db/user/password `quizzzone`).
2) Esporta le variabili:
```bash
export POSTGRES_HOST=localhost
export POSTGRES_DB=quizzzone
export POSTGRES_USER=quizzzone
export POSTGRES_PASSWORD=quizzzone
```
3) Installa e avvia:
```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```
Apri http://127.0.0.1:8000/.

## Variabili con .env
Copia il file `.env.example` in `.env` e personalizza se serve:
```bash
cp .env.example .env
```
Contiene i valori di default per Postgres e domini ammessi; per i tunnel Cloudflare include `*.trycloudflare.com` (adatta se vuoi restringere).

## Variabili ambiente principali
- `DJANGO_DEBUG` (default 1)
- `DJANGO_ALLOWED_HOSTS` (es. `localhost,127.0.0.1`)
- `DJANGO_SECRET_KEY` (obbligatoria in prod)
- `DJANGO_DB_ENGINE` (`postgres` o `sqlite` per esecuzioni locali/CI rapide)
- `DJANGO_SQLITE_NAME` (es. `:memory:` per run effimeri in CI)
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`

## Note
- I nickname e le icone sono unici per stanza; massimo 10 giocatori.
- WebSocket (Django Channels + Daphne) per aggiornamenti realtime della lobby.
- Il pulsante Gioca è visibile solo all’host con almeno 2 giocatori: avvia la modalità gioco di prova e chiude la stanza a nuovi ingressi.
