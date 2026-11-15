# Deploying Inherit

There are two ways to host Inherit. Both have been tested locally with the images in this repo.

| | Public demo mode | Full mode |
|---|---|---|
| Needs | any container host (no Docker access needed) | a machine with Docker (VM) |
| Analyzes | the bundled demo repo only | the demo repo **and uploaded zips** |
| Isolation | none needed: the demo is this project's own code | every run in a no-network, resource-limited Docker sandbox |
| Run cap | 6 per hour (configurable) | 12 per hour (configurable) |
| Good for | the hackathon's public demo URL | real use, or a demo that accepts uploads |

Whichever you choose, the site also serves a pre-computed **report for each of the seven demos**, so visitors see full results even when the hourly cap is reached. Two demos (`dates`, `vault`) contact the package index during their environment step, so the host needs outbound internet for those.

Set `NEBIUS_API_KEY`, `NEBIUS_BASE_URL`, `MODEL_REASONER` and `MODEL_WORKER` as **secrets** on the host (never commit them). Without them the app runs on the offline mock model and says so on every page.

---

## Option A: Hugging Face Spaces (public demo mode, free, no card)

1. Create an account at huggingface.co and a new **Space**:
   - SDK: **Docker**, template **Blank**
   - Hardware: **CPU basic** (free)
   - Visibility: **Public**
2. Create an access token with **write** permission (**Settings → Access Tokens**). Git asks for it as the password when you push.
3. Clone the empty Space next to this project, copy the files in, and push:

   ```bash
   git clone https://huggingface.co/spaces/<user>/<space> ../inherit-space
   python deploy/make_hf_space.py ../inherit-space
   cd ../inherit-space
   git add -A
   git commit -m "Deploy Inherit"
   git push
   ```

   The script copies only what the app needs (no tests, `.env` or databases) and writes the Space's `README.md` with the front matter Hugging Face requires (`sdk: docker`, `app_port: 7860`). Re-run the same steps to deploy updates.
4. In the Space's **Settings → Variables and secrets**, add the four `NEBIUS_*` / `MODEL_*` values as secrets.
5. The Space builds the root `Dockerfile` (public demo mode is its default); watch the **Logs** tab. The URL is `https://<user>-<space>.hf.space`.

Notes:
- Free Spaces sleep after a period of inactivity and wake on the next visit (first load takes longer). Check the URL works shortly before submitting and before judging starts.
- Runs are stored in `/tmp` and disappear on restart; the bundled sample reports are always available.

## Option B: Docker VM (full mode, e.g. Nebius AI Cloud)

### 1. Create the VM
- **OS:** Ubuntu 22.04 or 24.04
- **Size:** 2 vCPU and 4 GB RAM is enough (no GPU needed: models run on Token Factory)
- **Disk:** 20 GB
- **Firewall / security group:** allow inbound TCP **22** (SSH), **80**, and **443** if you use a domain
- Add your SSH public key when creating it, and note the VM's public IP

On Nebius AI Cloud this is a Compute virtual machine with a public IP address; any provider with Ubuntu VMs works the same way.

### 2. Copy the project to the VM

From your computer, in the folder that contains the project:

```bash
scp -r NVIDIA ubuntu@<vm-ip>:~/inherit
```

(Once the code is on GitHub, `git clone <repo-url> inherit` on the VM works instead.) The `.env` file is not copied by the clone; create it on the VM in the next step.

### 3. Run the setup script

```bash
ssh ubuntu@<vm-ip>
cd ~/inherit
sudo bash deploy/setup-vm.sh                    # http://<vm-ip>/
# or, with a domain whose DNS A record points at the VM:
sudo bash deploy/setup-vm.sh demo.example.com   # https://demo.example.com/ (automatic TLS via Caddy)
```

The script installs Docker, builds the sandbox and app images, starts the app with restart-on-reboot, and prints the URL. The first run creates `.env` from `.env.example`; put your Nebius values in it (`nano .env`) and run the script again. Re-running is also how you deploy updates.

### Useful commands

```bash
docker compose logs -f app      # live logs
docker compose restart app      # restart
docker compose down             # stop
```

How it works: the app container drives the host's Docker through `/var/run/docker.sock`. Repository copies are written to `/srv/inherit/tmp`, which is mounted at the same path in the app container and on the host, so the sandbox containers can bind-mount them. Target code always runs in the separate `inherit-sandbox` container as a non-root user with no network.

Security note: access to the Docker socket is powerful. Run full mode on a dedicated VM, not on a machine with other important workloads.

## Option C: temporary tunnel from your own machine (testing only)

To share a local instance briefly (e.g. for a teammate), you can expose `localhost:8000` with a tunnelling tool. It only works while your computer is on and awake, so it is **not suitable** as the submission's demo URL, which must stay up through the judging period.

## Local smoke test of the images

```bash
# public demo mode, as on Hugging Face
docker build -t inherit-app .
docker run --rm -p 7861:7860 inherit-app          # http://localhost:7861

# full mode
docker compose up -d app                           # http://localhost:8000
docker compose down
```

## Configuration reference

| Variable | Public default | Full default | Meaning |
|---|---|---|---|
| `INHERIT_PUBLIC_MODE` | `1` | `0` | `1` = demo repo only, uploads refused |
| `SANDBOX_BACKEND` | `local` | `docker` | where target code runs |
| `INHERIT_MAX_RUNS_PER_HOUR` | `6` | `12` | protects model credits; `0` = no cap |
| `INHERIT_RUNS_DIR` | `/tmp/inherit-runs` | `/srv/inherit/runs` | where run outputs are kept (last 20) |
| `PORT` | `7860` | `7860` (mapped to 8000) | port inside the container |
