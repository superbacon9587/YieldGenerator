# Shareable deployment

The Vercel configuration deploys the Vite frontend and FastAPI backend together on one domain. `/api/*` routes to the Python service; other requests go to the frontend. No local computer or tunnel is needed after deployment.

Deploy from the repository root with `vercel --prod` after signing in. Keep changes on the feature branch; deployment does not merge main. Select a personal Hobby project unless a different account/plan is intended.

`pyproject.toml` lists runtime-only Python dependencies. Local tests and analysis tools remain in requirements.txt. Python is 3.12. Reference CSV/JSON files are bundled with the function. POWER downloads use temporary storage in the serverless runtime, so cold instances may download weather again. The first backtest may take longer. This is a prototype deployment, not durable farm-data storage.

Before sharing, verify the public page, `/api/meta`, and a live Merced backtest. A static-only frontend deployment does not satisfy live backtesting. Do not publish a localhost API URL or substitute demo data for a failed backend.
