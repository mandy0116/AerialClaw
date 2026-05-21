# AerialClaw Quickstart

This guide is for users who need a repeatable first run before attempting the full PX4/Gazebo simulator.

## Choose by operating system first

| Goal | Windows PowerShell | Windows WSL2 Ubuntu | macOS | Linux |
|---|---:|---:|---:|---:|
| Quick demo / UI check | Docker mock | Docker mock | Docker mock | Docker mock |
| Local development | Native Python + Node | Python + Node | Python + Node | Python + Node |
| PX4 + Gazebo simulator | Use WSL2 | Recommended | Advanced | Recommended |

Do not run `scripts/*.sh` directly from native Windows PowerShell for PX4/Gazebo. Use WSL2 Ubuntu or Git Bash with LF line endings.

## 1. Fastest path: prebuilt Docker mock image

No local image build is required. This avoids failures while pulling `python:3.12-slim` or `node:22-slim` on user machines.

```bash
git clone https://github.com/XDEI-Group/AerialClaw.git
cd AerialClaw
docker compose up

# Equivalent plain Docker command:
# docker run --rm -p 5001:5001 yjf0307/aerialclaw:mock
```

Open `http://localhost:5001`, or verify in another terminal:

```bash
curl http://localhost:5001/api/status
```

Developer-only local build fallback:

```bash
docker compose -f compose.build.yml up --build
```

## 2. Local mock development

### Windows PowerShell

```powershell
git clone https://github.com/XDEI-Group/AerialClaw.git
cd AerialClaw

py -3.10 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m pytest

cd ui
npm install
npm run build
cd ..

$env:SIM_ADAPTER="mock"
python server.py
```

Optional Windows smoke gate:

```powershell
.\scripts\smoke_mock.ps1
```

### Windows CMD

```bat
py -3.10 -m venv venv
venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

cd ui
npm install
npm run build
cd ..

set SIM_ADAPTER=mock
python server.py
```

### macOS / Linux / WSL2 Ubuntu

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m pytest

cd ui
npm install
npm run build
cd ..

SIM_ADAPTER=mock python server.py
```

Optional Unix smoke gate:

```bash
bash scripts/smoke_mock.sh
```

## 3. PX4 + Gazebo guided simulation

Use this only after Docker mock or local mock works.

### Windows users

Use WSL2 Ubuntu, not native PowerShell:

```powershell
wsl --install -d Ubuntu-24.04
wsl
```

Then inside Ubuntu/WSL:

```bash
sudo apt update
sudo apt install -y git curl python3 python3-venv nodejs npm cmake build-essential

git clone https://github.com/XDEI-Group/AerialClaw.git
cd AerialClaw

bash scripts/doctor_gazebo.sh urban_rescue x500_lidar_2d_cam
bash scripts/setup_px4.sh
bash scripts/start_sim.sh urban_rescue x500_lidar_2d_cam
```

In another WSL terminal:

```bash
cd AerialClaw
source venv/bin/activate  # if using a virtual environment
SIM_ADAPTER=px4 PX4_GZ_WORLD=urban_rescue PX4_SIM_MODEL=x500_lidar_2d_cam python server.py
```

### Linux / macOS

```bash
bash scripts/doctor_gazebo.sh urban_rescue x500_lidar_2d_cam
bash scripts/setup_px4.sh
bash scripts/start_sim.sh urban_rescue x500_lidar_2d_cam
```

In another terminal:

```bash
source venv/bin/activate  # if using a virtual environment
SIM_ADAPTER=px4 PX4_GZ_WORLD=urban_rescue PX4_SIM_MODEL=x500_lidar_2d_cam python server.py
```

Verify:

```bash
curl http://localhost:5001/api/status
curl http://localhost:5001/api/sensor/status
bash scripts/doctor_gazebo.sh urban_rescue x500_lidar_2d_cam --live
```

## Windows CRLF / Bash troubleshooting

If you run Bash and see errors like these:

```text
$'\r': command not found
set: pipefail: invalid option name
syntax error near unexpected token `$'do\r''
```

fix the checkout line endings and retry from Git Bash or WSL2:

```bash
git config core.autocrlf false
git reset --hard HEAD
bash scripts/doctor_gazebo.sh urban_rescue x500_lidar_2d_cam
```

Fresh clones of this repository keep shell scripts as LF because `.gitattributes` pins `*.sh` line endings.
