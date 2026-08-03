# SwarmDeck web (Next.js)

The UI. The Python daemon (daemon/, port 8140) stays the backend/runner;
next.config.ts proxies /backend/* to it so cookie auth is same-origin.

    npm install
    npm run dev -- --port 3300    # dev (daemon must be running)
    npm run build && npm start    # production

The old single-file UI remains at http://localhost:8140/ as fallback.
