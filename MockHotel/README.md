# MockHotel

A small Dream Inn room-type price management system built with Next.js and PostgreSQL.

## Run with Docker

```bash
docker compose up --build
```

Open `http://localhost:3001`.

If your browser is not running on the GX10 host, forward the port first:

```bash
ssh -L 3001:localhost:3001 asus@<gx10-host>
```

Test account:

- Username: `manager`
- Password: `password123`

## Local development

```bash
npm install
cp .env.example .env.local
docker compose up postgres
npm run dev
```

MockHotel uses port `3001` so it can run next to `RevNest/WebApp` on port
`3000`. Its seed data mirrors the nine hotel room types in
`RevNest/Claw/data/sql/data.sql`.

Inside NemoClaw/OpenShell, host services are reached through
`http://host.openshell.internal:3001`, not `http://localhost:3001`.
