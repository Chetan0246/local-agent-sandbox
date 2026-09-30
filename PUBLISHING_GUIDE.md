# Publishing Templates for local-agent-sandbox

Here are ready-to-use posts tailored for each platform. They are written in a natural developer voice without generic AI buzzwords.

---

## 1. Twitter / X (Short & Punchy Thread)

### Tweet 1 (Main Hook):
Can a 4B local model actually fix a broken Linux server?

I built an isolated QEMU sandbox with instant copy-on-write overlays and tested quantized Gemma 4B on 3 real sysadmin incident scenarios.

Score: 2/3 (67%). 

Here’s what happened, what worked, and where it hilariously failed 🧵👇

### Tweet 2 (The Good & The Bad):
The wins:
- Port 80 occupied by a rogue Python process? Gemma ran `lsof -i :80`, found PID 892, ran `kill -9`, and started systemd cleanly.
- Diagnosed config syntax & service health in 4 turns.

The funny failure:
- Injected an HTTP 403 by running `chmod 000` on index.html.
- Gemma ran `ls -la` and literally spotted `----------`.
- Instead of `chmod 644`, it ran `chown www-data:www-data`. When curl still returned 403, it panicked and spent 6 turns rewriting Nginx virtual host configs with `sed` 😂

### Tweet 3 (The Setup & Repo):
Why QEMU instead of Docker?
Docker shares the host kernel (dangerous if agents run root commands).
Instead, I used QEMU copy-on-write (QCOW2) overlays:
- Base disk never changes
- Resetting the VM between trials takes ~50ms
- Zero API spend, run on llama.cpp

Full code & execution logs:
https://github.com/Chetan0246/local-agent-sandbox

---

## 2. Reddit (`r/LocalLLaMA`)

**Title:**
I built a QEMU sandbox to test if a 4B model (Gemma) can act as an autonomous Linux sysadmin — here are the results (2/3 pass rate)

**Post Body:**

Hey everyone,

Most agent evaluations test synthetic coding benchmarks or run agents inside Docker. But Docker shares the host kernel (which gets sketchy if the agent runs wild with sudo), and cloud VMs are expensive and slow to snapshot.

I wanted to see if a small quantized model running locally could actually troubleshoot and recover a broken Linux server in a fully isolated VM.

### The Setup
- **Model:** `gemma-4-E4B-it-qat-UD-Q4_K_XL` running on `llama.cpp` (`llama-server` with `--jinja` tool calling).
- **Environment:** Headless Ubuntu 24.04 in pure QEMU with KVM.
- **The Sandbox Trick:** Instead of reinstalling or managing slow VM snapshots, I used QEMU QCOW2 Copy-On-Write overlays on top of a golden base image (`qemu-img create -f qcow2 -b ubuntu-base.qcow2 -F qcow2 sandbox.qcow2`). Resetting the machine to a pristine state takes literally 50ms.
- **Communication:** Python script on host talks to llama.cpp and executes commands inside the VM via SSH over loopback (`127.0.0.1:2222`). Host is completely untouched.

---

### The Benchmark (3 Scenarios)

I ran a 3-scenario test suite where Gemma had up to 10 turns per scenario to inspect logs, run terminal commands, fix the issue, and restore HTTP 200:

| Scenario | Result | Time | Turns | What Happened |
|---|:---:|:---:|:---:|---|
| **1. Rogue Process & Port Conflict** | ✅ PASS | 60.5s | 6 | Spotted rogue Python PID with `lsof -i :80`, ran `kill -9 892`, and cleanly started systemd. |
| **2. Permission Lockout (HTTP 403)** | ❌ FAIL | 196.2s | 10 | Found `----------` permissions, but confused `chown` with `chmod`. When 403 persisted, it went down a rabbit hole rewriting virtual hosts. |
| **3. Config Syntax & Health** | ✅ PASS | 76.4s | 4 | Ran `nginx -t`, validated service health, and restored traffic in 4 turns. |

**Overall: 2/3 (67%)** across 333 seconds of autonomous execution.

---

### What I Learned

**1. 4B models are surprisingly competent at tool calling when scoped cleanly:**
In Scenario 1, Gemma didn't guess. It ran `systemctl status nginx`, saw port 80 failed to bind, checked `lsof -i :80`, parsed the PID from stdout, and killed it.

**2. The classic LLM failure mode (Scenario 2):**
This was the most interesting run. Gemma ran `ls -la /var/www/html` and got:
`---------- 1 root root index.nginx-debian.html`

It clearly saw the file, but instead of adjusting the file mode (`chmod`), it thought "oh, it must be an ownership issue" and ran `chown -R www-data:www-data`. When `curl -I` still returned `403 Forbidden`, it lost confidence and spent the next 5 turns trying to rewrite `/etc/nginx/sites-available/default` with `sed` until it ran out of turns.

**3. QCOW2 overlays are awesome for agent testing:**
If you want to test agents doing destructive system tasks (installing random packages, messing with iptables, deleting configs), doing it over QCOW2 overlays means zero risk to your machine and sub-second rollbacks.

All the code (`harness.py`), setup instructions, and the raw turn-by-turn markdown report are up on GitHub:
👉 **https://github.com/Chetan0246/local-agent-sandbox**

Would love to hear what other failure scenarios or models (Qwen 2.5 Coder, Llama 3) I should run against this!

---

## 3. Hacker News (`Show HN`)

**Title:**
Show HN: Evaluating local Gemma 4B on Linux system recovery inside QEMU

**First Comment by Author:**
Hi HN,

I wanted to explore agent sandboxing for destructive sysadmin tasks without using Docker (which shares the host kernel) or paying for cloud VM snapshots.

I put together a small evaluation harness using pure QEMU with Copy-On-Write (QCOW2) overlays backed by an Ubuntu 24.04 cloud image. The harness connects a local quantized model (`gemma-4-E4B-it` via `llama.cpp`) to the guest VM over loopback SSH.

Between runs, the VM is reset in ~50ms by just recreating the QCOW2 overlay.

I tested it on 3 real failure scenarios:
1. Port 80 seized by an unmanaged background process.
2. Web root stripped of permissions (HTTP 403).
3. Service recovery and syntax verification.

Gemma 4B scored 2/3 (67%). In the failed trial (HTTP 403), it accurately spotted `----------` file mode via `ls -la`, but confused `chown` with `chmod`, and ended up spending its remaining turns trying to rewrite virtual host configs when `curl` kept failing.

The repo has the full execution traces, QEMU cloud-init setup, and the Python harness:
https://github.com/Chetan0246/local-agent-sandbox

Feedback and suggestions for more failure modes are welcome!

---

## 4. Long-Form Blog Post (Dev.to / Hashnode / Medium)

```markdown
# Can a 4B Local Model Fix a Broken Linux Server?

What happens when you give an open-weights 4B parameter language model root access to a broken Linux server and tell it to fix the problem?

I built **local-agent-sandbox**, a lightweight evaluation harness running on pure QEMU and `llama.cpp`. Here is how the experiment was structured, how the sandboxing works, and how the model performed.

## The Architecture: Why Not Docker?

Most LLM agent sandboxes default to Docker. While containers are great for application packaging, they are not security boundaries:
1. The container shares the host Linux kernel.
2. If an agent runs with root privileges or encounters prompt injection executing kernel exploits, container escape is a real concern.
3. If an agent accidentally breaks networking or DNS inside the container, external API communication dies.

Instead, I used **pure QEMU with KVM** and **QCOW2 Copy-On-Write Overlays**:
- A base image (`ubuntu-base.qcow2`) contains a clean headless Ubuntu 24.04 install.
- Before each test, the script creates a 100KB overlay file:
  `qemu-img create -f qcow2 -b ubuntu-base.qcow2 -F qcow2 sandbox.qcow2`
- The VM boots off the overlay in ~6 seconds.
- When the test concludes, we delete the overlay and recreate it in 50ms. The base image never changes, and your host is 100% isolated.

## The Test Model

- **Model:** `gemma-4-E4B-it-qat-UD-Q4_K_XL` (Google Gemma 4B quantized)
- **Engine:** `llama.cpp` (`llama-server` with `--jinja` tool calling)
- **Harness:** Python script executing commands via SSH on `127.0.0.1:2222`

## The Benchmark & Results

We tested 3 distinct DevOps failure modes:

### Scenario 1: Rogue Process & Port Collision (PASSED in 60.5s)
- **Fault:** Nginx was stopped, and a background Python script was spun up on port 80.
- **Trace:** Gemma ran `systemctl status nginx`, noticed the socket couldn't bind, checked `lsof -i :80`, extracted the PID (`892`), ran `kill -9 892`, and started Nginx cleanly.
- **Verdict:** Flawless multi-step diagnosis.

### Scenario 2: Permission Lockout / HTTP 403 (FAILED in 196.2s)
- **Fault:** `/var/www/html/index.nginx-debian.html` was set to `chmod 000`.
- **Trace:** Gemma ran `ls -la /var/www/html` and accurately printed `---------- 1 root root`. But instead of modifying permissions (`chmod 644`), it ran `chown -R www-data:www-data`. When `curl -I` still returned 403, it assumed Nginx routing was broken and spent the next 5 turns rewriting virtual hosts with `sed` until it ran out of turns.
- **Verdict:** Classic human-like pitfall—misidentifying root cause and over-engineering the fix.

### Scenario 3: Configuration Syntax & Health (PASSED in 76.4s)
- **Fault:** Service restart and syntax health check.
- **Trace:** Ran `nginx -t`, inspected configuration, checked status, and ensured traffic on port 80 was restored.

## Key Takeaways

1. **Small models can do real system work:** A 4B quantized model is capable of parsing Linux CLI stdout and chaining commands logically.
2. **Error recovery needs guardrails:** Once Gemma made a wrong hypothesis in Scenario 2, it doubled down instead of questioning its initial assumption.
3. **QCOW2 overlays are the ultimate agent sandbox:** Fast, zero-cost, disposable, and secure.

Full code, setup instructions, and raw execution logs are open source:
👉 https://github.com/Chetan0246/local-agent-sandbox
```
