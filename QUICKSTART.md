# AerialClaw Quickstart

This quickstart contains only the repository paths that are verified for the public package.

## 1. Container mock mode

No local image build is required.

```bash
git clone https://github.com/XDEI-Group/AerialClaw.git
cd AerialClaw
docker compose up

# Equivalent plain Docker command:
# docker run --rm -p 5001:5001 xdei/aerialclaw:mock
```

Verify:

```bash
curl http://localhost:5001/api/status
```

Open:

```text
http://localhost:5001
```

## 2. Local mock development

```bash
git clone https://github.com/XDEI-Group/AerialClaw.git
cd AerialClaw

python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pytest
python -m pytest

cd ui
npm install
npm run build
cd ..

SIM_ADAPTER=mock python server.py
```

Verify in another terminal:

```bash
curl http://localhost:5001/api/status
```

Optional smoke gate:

```bash
bash scripts/smoke_mock.sh
```

## Optional: PX4 + Gazebo simulator integration

You can stop after section 1 or section 2. This is not a required third step. Use this path only when you want to connect AerialClaw to a full PX4 + Gazebo simulator. Validate the target simulator host before using simulator-specific commands.

See:

```text
docs/SIMULATION_SETUP.md
```
