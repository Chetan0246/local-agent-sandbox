# local-agent-sandbox

A lightweight, 100% offline evaluation harness to test local LLM agents on autonomous Linux system repair tasks inside isolated QEMU virtual machines.

Instead of running agents in Docker (which shares the host kernel) or paying for cloud VMs, this project uses **pure QEMU with Copy-On-Write (QCOW2) overlays**. Each trial runs in a disposable VM layer that resets in ~50 milliseconds.

---

## Benchmark Results: Gemma 4B (`gemma-4-E4B-it-qat-UD-Q4_K_XL`)

We ran a 3-scenario test suite where Gemma interacted via tool-calling against a headless Ubuntu 24.04 server in QEMU:

| Scenario | Problem Type | Result | Time | Turns | What Happened |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **1. Rogue Process & Port Collision** | Socket conflict | **PASSED** | 60.5s | 6 | Ran `lsof -i :80`, spotted the rogue Python process, killed it with `kill -9`, and started systemd cleanly. |
| **2. Permission Lockout (HTTP 403)** | File mode error | **FAILED** | 196.2s | 10 | Spotted `----------` permissions, but confused `chown` with `chmod`. When 403 persisted, it went down a rabbit hole editing virtual hosts. |
| **3. Config Syntax & Health** | Service recovery | **PASSED** | 76.4s | 4 | Ran `nginx -t`, validated syntax, verified health, and restored HTTP traffic. |

**Overall Score: 2/3 (67%)** across 333 seconds.

Full execution trace is documented in [`REPORT.md`](REPORT.md).

---

## Why QEMU Overlays?

Most agent sandboxes either use Docker (which is risky if the agent runs untrusted commands with root privileges) or heavyweight cloud VMs (slow and expensive).

This setup uses a base disk image (`ubuntu-base.qcow2`) and spawns a temporary overlay on top:
```bash
qemu-img create -f qcow2 -b ubuntu-base.qcow2 -F qcow2 sandbox.qcow2
```
To reset the VM after a test, we just delete the overlay and recreate it in 0.05 seconds. The base image remains untouched, and the host is isolated via QEMU user networking (`127.0.0.1:2222`).

---

## Prerequisites

- Linux host with KVM enabled (`/dev/kvm`)
- QEMU (`qemu-system-x86`, `qemu-utils`, `cloud-image-utils`)
- `llama.cpp` running any OpenAI-compatible server (e.g., on port 8080)
- Python 3 with `openai` package (`pip install openai`)

---

## Setup & Running

### 1. One-Time Golden Base Setup

Generate a keypair and build the cloud-init base:
```bash
ssh-keygen -t ed25519 -f ./vm_key -N "" -C "agent-sandbox"
wget https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img -O ubuntu-base.qcow2
qemu-img resize ubuntu-base.qcow2 10G
```

Create `user-data` with your public key and build the ISO:
```bash
python3 -c "
key = open('vm_key.pub').read().strip()
content = f'''#cloud-config
users:
  - name: ubuntu
    gecos: Ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - {key}
'''
open('user-data', 'w').write(content)
"
cloud-localds cloud-init.iso user-data
```

Boot the base once to let cloud-init finish and install Nginx:
```bash
qemu-system-x86_64 -enable-kvm -m 2048 -smp 2 \
  -drive file=ubuntu-base.qcow2,if=virtio \
  -drive file=cloud-init.iso,format=raw,if=virtio \
  -netdev user,id=net0,hostfwd=tcp:127.0.0.1:2222-:22 \
  -device virtio-net-pci,netdev=net0 -display none -daemonize
```
Once SSH is up on port 2222, install packages and power off:
```bash
ssh -i vm_key -p 2222 -o StrictHostKeyChecking=no ubuntu@127.0.0.1 \
  "sudo apt update && sudo apt install -y nginx curl && sudo poweroff"
```

### 2. Start Your Local LLM (llama.cpp)
```bash
./llama-server -m /path/to/model.gguf --port 8080 --host 127.0.0.1 -c 16384 --jinja
```

### 3. Run the Benchmark
```bash
python3 harness.py
```
Results and full execution logs will be written to `REPORT.md` and `benchmark_results.json`.
