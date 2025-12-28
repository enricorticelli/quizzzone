# Quizzzone

Quiz multiplayer da salotto: l’host crea una stanza dal PC, i giocatori si uniscono da mobile via codice/QR scegliendo nickname e icona unici (max 10). Lo schermo comune mostra domanda + risposte + classifica, i telefoni servono solo per scegliere o rispondere a turno. UI in italiano.

## Stack tecnico
- Django + Django Channels + Daphne
- WebSocket per lobby (`/ws/stanza/<code>/`) e gioco (`/ws/stanza/<code>/gioco/`), con fallback a polling
- Postgres di default (SQLite abilitabile via `DJANGO_DB_ENGINE=sqlite` e `DJANGO_SQLITE_NAME`)
- Front-end HTML/CSS/JS vanilla con view toggle (schermo comune vs dispositivo giocatore)

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

4) Deploy su tunnel Cloudflare (opzionale):
```bash
cloudflared tunnel --url http://localhost:8000
```

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

## Schermate e UX
- **Schermo comune (desktop/proiettore):** mostra sempre classifica a destra e, a sinistra, domanda corrente con risposte pubbliche ed esito. La griglia 5x5 (materia x livello) è sempre visibile per seguire l’andamento.
- **Dispositivo giocatore:** quando non è il tuo turno vedi solo “In attesa del tuo turno”. Quando è il tuo turno e devi scegliere compare solo la griglia responsive; quando devi rispondere compaiono solo le opzioni, nessun’altra distrazione.
- **Host:** è il primo giocatore della stanza; il pulsante “Gioca” è visibile solo all’host con almeno 2 giocatori.

## Regole di gioco
- **Partecipanti:** massimo 10 giocatori per stanza, nickname e icone unici.
- **Set di domande richiesto:** 5 materie (`Storia`, `Scienza`, `Cultura generale`, `Sport`, `Geografia`) x 5 livelli (1-5). All’avvio il sistema estrae una domanda attiva per ogni combinazione (totale 25); se manca anche una sola combinazione la partita non parte.
- **Punteggio:** i punti corrispondono al livello della domanda (1–5).
- **Turni:** si parte da un giocatore casuale. Stato `choosing`: il giocatore di turno sceglie una cella libera della griglia. Stato `answering`: vede solo sul proprio device le tre opzioni A/B/C, seleziona e invia. Se risponde correttamente resta lui a scegliere la prossima domanda; se sbaglia il turno passa al giocatore successivo (ordine di ingresso). Ogni cella può essere usata una sola volta.
- **Classifica e finale:** la classifica è aggiornata in tempo reale e ordinata per punteggio (poi nickname). La partita termina quando finiscono le 25 domande; mostra il vincitore sullo schermo comune.

## API di gioco (HTTP)
- `GET /stanza/<code>/gioco/state/` – stato completo della partita
- `POST /stanza/<code>/gioco/scegli/` – scelta categoria/livello (solo giocatore di turno, stato `choosing`)
- `POST /stanza/<code>/gioco/rispondi/` – invio risposta A/B/C (solo giocatore di turno, stato `answering`)

## Note
- I nickname e le icone sono unici per stanza; massimo 10 giocatori.
- WebSocket (Django Channels + Daphne) per aggiornamenti realtime della lobby.
- Il pulsante Gioca è visibile solo all’host con almeno 2 giocatori: avvia la modalità gioco e chiude la stanza a nuovi ingressi.
