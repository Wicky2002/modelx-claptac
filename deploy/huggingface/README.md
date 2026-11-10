# Hosting ATLAS on Hugging Face Spaces

ATLAS runs as one Docker container (API, agents and console on port 8000), so it deploys as a
**Docker Space**. The free CPU hardware is enough. PyTorch is not in the image, and the agents fall
back to their rules when no trained weights are loaded.

## Steps

1. Create the Space on huggingface.co: **New Space**, SDK **Docker**, blank template, CPU basic.
2. Create an access token with **write** permission (Settings, Access Tokens).
3. Install Git LFS once: `git lfs install`.
4. From the repository, on the commit you want to deploy:

   ```bash
   bash deploy/huggingface/push.sh <hf-username>/<space-name>
   ```

   Git asks for your username, then the token as the password.
5. Watch the build log. It takes a few minutes. The Space opens on the console.

## Things to know

- **Storage resets** when the Space restarts or sleeps. That's fine for a demo. For data that survives
  restarts, add persistent storage in the Space settings and set the Space variable
  `DATABASE_URL=sqlite:////data/atlas.db`.
- **Open demo mode.** With no `ATLAS_TOKENS` set, anyone with the link can approve decisions and change
  AI model settings. To limit that, add `ATLAS_TOKENS` as a Space **secret**, in the format shown in the
  main README.
- **AI key.** The app works without one. To enable the language-model features, add
  `ANTHROPIC_API_KEY` as a Space secret. Never commit it.
- **Container user.** Spaces run containers as user 1000, which is why the Dockerfile creates `atlas`
  with that ID. A local Docker volume created by an older image belongs to user 10001. Run
  `docker compose down -v` once to recreate it.
- **Field sensors** can send to the Space's HTTPS address (`/ingest/sensor`) over HTTP. MQTT and LoRa
  need a broker or gateway you run yourself.
