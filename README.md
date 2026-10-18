# TerraBid — Complete Project (No Docker)

This archive preserves the project's source code for the backend, original frontend, and Streamlit frontend, while removing Docker configuration, Git history, local environment files, and generated build artifacts.

## Recommended quick start: standalone Streamlit demo

The Streamlit edition has been updated to run **without Docker, without the FastAPI backend, and without PostgreSQL or Redis**. It uses local SQLite and automatically seeds eight sample parcels, live/upcoming/ended auctions, and sample bid history.

### Windows

1. Install Python 3.11 or 3.12: https://www.python.org/downloads/
2. Open Command Prompt in this project folder.
3. Run:

   ```cmd
   cd frontend_streamlit
   python -m venv .venv
   .venv\Scripts\activate
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   streamlit run app.py
   ```

4. Visit http://localhost:8501.

The SQLite database is created automatically at `frontend_streamlit/data/terrabid_demo.sqlite3`. Sample bids are saved locally and persist between restarts. Use the app's About page to reset demo data.

## What's included

- `frontend_streamlit/`: standalone no-Docker demo, sample data initialization, interactive parcel map, search and filters, auction activity and demo bidding.
- `backend/`: original FastAPI backend source retained for future integration.
- `frontend/`: original web frontend source retained.
- `.env.example`: example configuration only; no real `.env` or secrets are included.

## Important distinction

The no-Docker Streamlit demo is a local prototype. All property details, prices, bidder names, verification labels, and bids are illustrative synthetic data. It does not provide secure authentication, real-money bidding, legal/title verification, or production-grade multi-user auction concurrency.

The original FastAPI and web frontend source is included for completeness, but it is **not started by the standalone demo**. Running that separate backend may require PostgreSQL/PostGIS, Redis, and configuration changes depending on the original backend code. Docker files have been removed as requested.
