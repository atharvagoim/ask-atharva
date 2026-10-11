# Ask Atharva

A calm personal productivity assistant. Talk to it in plain English, or use the pages directly:

- **Today:** a greeting, your day at a glance, and one box to ask anything.
- **Chat:** "add *prepare demo* for Friday", "what's on tomorrow?", "make 5 slides on time blocking", "analyse sales.xlsx and draw a chart". It remembers the conversation.
- **Todos:** add, tick off (with undo), edit, set priority and due dates.
- **Calendar:** your own built-in calendar: a month view, a list for each day, and a quick sheet to add, edit or delete events, here or by asking in chat.
- **Files:** drop in spreadsheets or meeting notes, and download the slides, charts and reports it makes.
- **Settings:** your name and profile photo (times are always India Standard Time). The AI key lives on the server, so people using the app never see or handle it.

## Start it (one command)

You need **Python 3.11+**.

```bash
pip install -r requirements.txt
python run.py
```

Your browser opens at `http://localhost:8000`. If you use [uv](https://docs.astral.sh/uv/), run `uv sync` and then `uv run python run.py`.

**First time:** paste a free Groq key (from [console.groq.com/keys](https://console.groq.com/keys)) into the box the app shows you. Todos, Files and Calendar work even without a key.

## Accounts and database (MongoDB)

Everyone signs up with an email and password, and each account only sees its own todos, chats, files, settings and calendar events. Data lives in MongoDB.

1. Create a free cluster at [MongoDB Atlas](https://www.mongodb.com/atlas), add a database user, and under **Network Access** allow your IP (use `0.0.0.0/0` when hosting on Vercel).
2. Copy the connection string (**Connect → Drivers**) into `.env` as `MONGODB_URI=...` and start the app. The first screen asks you to create your account.
3. `ALLOW_SIGNUP=false` closes sign-ups once you and your people are in. The AI runs on the server's `GROQ_API_KEY` (optionally `MODEL`), shared by every account and never shown in the app. Chat shows a friendly "switched off" note until it's set.

## Put it online (Vercel)

1. Set these in your Vercel project (Settings → Environment Variables): `MONGODB_URI`, `GROQ_API_KEY`, and a long random `SECRET_KEY`.
2. Deploy with `npx vercel --prod` from this folder, or push to GitHub and import the repo.

Hosted limits: uploads are capped at 4 MB (Vercel's request limit), and a reply can take up to 2 minutes.

## Where things live

```
ask-atharva/
├── run.py              start here: python run.py
├── .env                your settings (created on first run; the Settings page edits it)
├── data/               your todos, chats, uploads, generated files (created automatically)
├── app/
│   ├── main.py         the web server (API + interface on one port)
│   ├── api/routes.py   JSON API used by the interface
│   ├── agent/          the AI: chat loop (LangGraph), model choice, prompts
│   ├── tools/          what the AI can do: todos, calendar, files, slides, meetings
│   ├── services/       the real work, shared by the AI and the pages
│   └── web/            the interface: index.html, app.css, app.js (no build step)
└── tests/              pytest suite, using a stand-in AI so no key is needed
```

## Good to know

- On your computer it runs only at `127.0.0.1`, so nobody else on your network can open it. Online, accounts keep everyone's data separate.
- Numbers in spreadsheet answers come from pandas, never from the AI's imagination.
- Deleting a todo, event or file always asks first. Everything else just happens.
- Run the tests with `pip install pytest httpx && python -m pytest`.
