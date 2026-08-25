1. The README (every project needs this)

This is the front door. A solid README usually has:

Project name + one-line description — what it does and why it exists
Status/badges (build passing, version, license) — optional but common
Quick start — minimum steps to install and run it
Installation — dependencies, environment setup, config
Usage examples — real commands or code snippets, not just prose
Configuration — env vars, config files, flags
Architecture overview (brief) — or a link to deeper docs
Contributing guidelines — if others will touch the code
License

2. Architecture Decision Records (ADRs)

For any nontrivial technical choice (why Postgres over Mongo, why microservices vs. monolith), teams often keep short, timestamped documents explaining:

Context — what problem prompted the decision
Decision — what was chosen
Consequences — tradeoffs, what you're giving up

These live in a folder like /docs/adr/0001-use-postgres.md. They're valuable because they capture why, which code alone never shows.

3. Design docs / RFCs (before building something big)

Before writing code for a significant feature, many engineering orgs write a short design doc covering:

Problem statement
Goals / non-goals
Proposed approach (with alternatives considered)
Risks, edge cases, rollout plan


4. API documentation

If your project exposes an API, this is usually auto-generated or semi-generated:

REST → OpenAPI/Swagger spec
GraphQL → schema introspection
Libraries → docstrings/JSDoc/Javadoc turned into generated docs (Sphinx, JSDoc, Godoc, etc.)

5. Code-level comments

Minimal narration of what the code does (the code should mostly speak for itself), but comments explaining why something non-obvious was done, plus proper docstrings for public functions/classes.

6. Runbooks / operational docs

For anything deployed to production: how to deploy, roll back, monitor, and what to do when it breaks at 3am. Often called runbooks or playbooks.

7. Changelog

A CHANGELOG.md tracking what changed per version — Keep a Changelog is a widely used convention.

# GYM AI API
Gym AI is an AI powered Gym assistant/coach for people who workout at the gym. It helps them track their progress and gives them information they need about exercises.

## Live Deployment
The fast API server is deployed on a free instance on [Render](https://render.com). This means that the service spins down with inactivity and would require a few mins to spin back up when you visit the URL or make request

Live URL: https://gym-ai-backend-h26r.onrender.com
Live API Docs: [Docs](https://gym-ai-backend-h26r.onrender.com/docs)

## Quick Start (How ro run locally)
- Clone the repository
- Ensure that your have python and UV installed on your system
- From the root directory, run ``uv add`` to install dependencies
- You must either have Postgres or Docker installed on your local machine.
    If docker is installed, then simply run the command ``docker compose up -d`` to start up a postgres DB inside a container. 
    If you have Postgres installed then simply input it's connection details to the required variables in the
    .env file.
- To populate Pinecone vector store, run ``uv run python -m app.services.rag.ingest``
- To start the dev server, run ``uv run fastapi dev main.py``

## Configuration 
Create a .env file in the root of the project and add the variables in .env.example nd populate your own values
Some important modifications:

- The project makes use of psycopg driver to talk to the database. Therefore, you must add ``+psycopg`` to the DATABASE_URL variable

```
postgresql+asyncpg://user:password@host/dbname
│           │
│           └── which driver to use to connect
└── which database type
```

- Run the following command in your terminal to generate your own SECRET_KEY variable:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## API Docs
Once the server is running successfully, in your browser, visit http://localhost:8000/docs to view the documented API routes or view live docs [here](https://gym-ai-backend-h26r.onrender.com/docs)

## Architecture

### Server
Python (FastAPI)
### Vector store
Pinecone
### Database 
PostgreSQL
### ORM
SQLAlchemy
### Migrations 
Database migrations are handled using Alembic.
Run the following command in the terminal to run migrations and create all DB tables (ensure database env vars have been added to your .env file):
```bash
alembic upgrade head
```