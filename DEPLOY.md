# Running LORE 24/7

LORE's public agent talks to ASI:One through its Agentverse **mailbox**, so it only needs
outbound internet. It can run anywhere that keeps a process alive. It needs no open port and no domain.

> Run **one** copy at a time. Two copies with the same address share one mailbox and will
> race for messages. Stop the Mac copy once the cloud copy is up.

## Option A: your Mac (fastest)

```bash
sh scripts/run_forever.sh
```

This keeps the Mac awake while LORE runs and restarts LORE if it crashes. Logs are in `data/agents.log`.
Keep the charger in and the lid **open**: closing the lid still puts a Mac to sleep.
If the lid must close, run `sudo pmset -a disablesleep 1`, and run `sudo pmset -a disablesleep 0` afterwards to undo it.

## Option A2: Docker on a Mac (what the demo machine runs)

```bash
brew install colima docker && colima start --cpu 2 --memory 2
docker build -t lore .
docker run -d --name lore --restart unless-stopped \
  -e LORE_SEED="$(cat data/.agent_seed)" -e LORE_DB=/app/state/lore.db \
  -v lore-state:/app/state -p 127.0.0.1:8000:8000 lore
brew services start colima        # Docker, and so LORE, come back after a reboot or login
```

`docker logs -f lore` shows the agents; `docker restart lore` restarts them. The `lore-state`
volume keeps memories and the audit log across restarts. The Mac must still stay on, awake and online.

## Option B: the cloud (Railway, from this GitHub repo)

1. Copy your agent seed so the cloud agent keeps the **same address**:
   ```bash
   pbcopy < data/.agent_seed
   ```
   Treat it like a password: it *is* your agents' private key. Never commit it or paste it into a chat.
2. Go to **railway.com**, sign in with GitHub, choose **New Project → Deploy from GitHub repo**, and pick `LORE`.
   Railway finds the `Dockerfile` by itself.
3. In the service's **Variables**, add:
   - `LORE_SEED` = paste the seed from step 1
   - optionally `LORE_DISPLAY_NAME`, `LORE_AVATAR_URL`, `ASI1_API_KEY`
4. Deploy. The logs should list the same `lore` address as `python run_agents.py` prints locally,
   and must **not** say "Agent mailbox not found". The mailbox belongs to the address, so it carries over.
5. Stop the Mac copy.

The memory is rebuilt from `data/sample_repo` on every start. To keep imported repos and audit
history across restarts, attach a volume at `/app/data`.

The same Dockerfile works on Render (Background Worker), Fly.io, or any VM:

```bash
docker build -t lore .
docker run -d --restart=always -e LORE_SEED="$(cat data/.agent_seed)" lore
```
