# Persistence and restore

Set `DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME` for PostgreSQL. For local development without PostgreSQL, the server uses `sqlite:///./storyverse.db`. Never commit credentials.

Run: `cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload`.

Mobile: `cd mobile && npm install && EXPO_PUBLIC_API_URL=http://YOUR_LAN_IP:8000 npm start`. Android emulator can use `http://10.0.2.2:8000`. A physical phone needs a reachable HTTPS endpoint or local LAN address.

Each message is written to the database immediately. Manual checkpoints reference immutable message positions. Restoring always creates a separate branch and leaves the original room untouched. This is not yet production-ready: authentication, room membership permissions, database migrations, real-time multiplayer, background/offline queueing, and AI-generated world-state snapshots are not implemented. Do not expose this API publicly without authentication and authorization.
