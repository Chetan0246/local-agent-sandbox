#!/usr/bin/env python3
import json
import os
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone
from openai import OpenAI

WORKSPACE_DIR = os.path.expanduser("~/qemu-sandbox")
LLAMA_CPP_URL = "http://127.0.0.1:8080/v1"
MODEL_NAME = "models/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf"
SSH_KEY = os.path.join(WORKSPACE_DIR, "vm_key")
SSH_PORT = 2222

client = OpenAI(base_url=LLAMA_CPP_URL, api_key="dummy")


class VMController:
    def __init__(self):
        self.qemu_process = None

    def reset_overlay(self):
        """Creates a fresh copy-on-write overlay from the golden base in milliseconds."""
        self.stop()
        sandbox_img = os.path.join(WORKSPACE_DIR, "sandbox.qcow2")
        base_img = os.path.join(WORKSPACE_DIR, "ubuntu-base.qcow2")
        if os.path.exists(sandbox_img):
            os.remove(sandbox_img)
        subprocess.run(
            [
                "qemu-img",
                "create",
                "-f",
                "qcow2",
                "-b",
                base_img,
                "-F",
                "qcow2",
                sandbox_img,
            ],
            check=True,
            capture_output=True,
        )

    def start(self):
        """Starts QEMU with the isolated overlay."""
        self.reset_overlay()
        cmd = [
            "qemu-system-x86_64",
            "-enable-kvm",
            "-m",
            "2048",
            "-smp",
            "2",
            "-drive",
            f"file={os.path.join(WORKSPACE_DIR, 'sandbox.qcow2')},if=virtio",
            "-netdev",
            f"user,id=net0,hostfwd=tcp:127.0.0.1:{SSH_PORT}-:22",
            "-device",
            "virtio-net-pci,netdev=net0",
            "-display",
            "none",
            "-daemonize",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Failed to start QEMU: {res.stderr}")
        self._wait_for_ssh()

    def _wait_for_ssh(self, timeout=60):
        start = time.time()
        while time.time() - start < timeout:
            try:
                with socket.create_connection(("127.0.0.1", SSH_PORT), timeout=1):
                    time.sleep(1)
                    return True
            except (ConnectionRefusedError, socket.timeout):
                time.sleep(1)
        raise TimeoutError("QEMU VM failed to expose SSH in time.")

    def run_cmd(self, command: str, timeout: int = 40) -> str:
        """Executes a command inside the VM via SSH. Strictly isolated from host."""
        ssh_cmd = [
            "ssh",
            "-i",
            SSH_KEY,
            "-p",
            str(SSH_PORT),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "LogLevel=ERROR",
            "ubuntu@127.0.0.1",
            f"sudo bash -c '({command}) 2>&1 | tail -n 40'",
        ]
        try:
            res = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)
            out = res.stdout.strip()
            return out if out else "[Command completed with no output]"
        except subprocess.TimeoutExpired:
            return "[Error: Command timed out]"
        except Exception as e:
            return f"[Error: {e}]"

    def stop(self):
        """Kills any running QEMU instances bound to SSH_PORT."""
        subprocess.run(["pkill", "-9", "-f", f"hostfwd=tcp:127.0.0.1:{SSH_PORT}"], capture_output=True)
        time.sleep(0.5)


tools = [
    {
        "type": "function",
        "function": {
            "name": "execute_shell",
            "description": "Execute a bash shell command as root inside the target Ubuntu VM to inspect logs, edit files, or manage services.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command, e.g., 'systemctl status nginx', 'nginx -t', 'chmod 644 ...', 'sed -i ...'",
                    }
                },
                "required": ["command"],
            },
        },
    }
]


def run_single_trial(scenario, vm: VMController, max_turns: int = 10):
    print(f"\n==================================================")
    print(f"▶ Running Scenario: {scenario['name']}")
    print(f"==================================================")

    print("1. Spawning fresh isolated VM overlay...")
    vm.start()

    print("2. Injecting fault into VM...")
    scenario["inject"](vm)

    print("3. Handing control to Gemma agent...")
    start_time = time.time()
    trial_log = []

    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert autonomous Linux SysAdmin. Your objective is to diagnose and resolve issues on a headless Ubuntu server.\n"
                "Use the execute_shell tool to inspect logs, find root causes, edit configuration files, fix permissions, and restart services.\n"
                "When you have verified the service is running properly, respond with 'STATUS: RECOVERY_COMPLETE'."
            ),
        },
        {"role": "user", "content": scenario["problem"]},
    ]

    turn_count = 0
    for turn in range(1, max_turns + 1):
        turn_count = turn
        print(f"\n[{scenario['name']} | Turn {turn}/{max_turns}] Consulting Gemma...")
        try:
            resp = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=tools,
                temperature=0.1,
            )
        except Exception as e:
            print(f"API Error with llama.cpp: {e}")
            break

        msg = resp.choices[0].message
        messages.append(msg)

        if msg.content:
            print(f"Agent Thought:\n{msg.content}")
            trial_log.append({"turn": turn, "type": "thought", "text": msg.content})
            if "RECOVERY_COMPLETE" in msg.content:
                print("🎯 Agent declared recovery complete.")
                break

        if msg.tool_calls:
            for call in msg.tool_calls:
                try:
                    args = json.loads(call.function.arguments)
                    cmd = args.get("command", "")
                except Exception:
                    cmd = call.function.arguments

                print(f"  ⚡ VM Command: {cmd}")
                output = vm.run_cmd(cmd)
                print(f"  ↳ Output:\n{output}\n")

                trial_log.append({"turn": turn, "type": "action", "cmd": cmd, "output": output})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": output,
                    }
                )

    # Automated Independent Verification
    print("4. Running independent verification probe...")
    success = scenario["verify"](vm)
    total_time = round(time.time() - start_time, 2)
    print(f"   Outcome: {'✅ PASSED' if success else '❌ FAILED'} in {total_time}s ({turn_count} turns)")

    vm.stop()

    return {
        "name": scenario["name"],
        "success": success,
        "duration_seconds": total_time,
        "turns_used": turn_count,
        "log": trial_log,
    }


def main():
    scenarios = [
        {
            "name": "Scenario 1: Port Collision & Rogue Process",
            "problem": "Nginx is stopped, and starting it fails because port 80 is occupied by a rogue process. Identify the process holding port 80, kill it, start nginx via systemctl, and ensure it serves HTTP requests.",
            "inject": lambda vm: vm.run_cmd("systemctl stop nginx && (python3 -m http.server 80 >/dev/null 2>&1 &) && sleep 1"),
            "verify": lambda vm: "PASS" in vm.run_cmd("systemctl is-active nginx && curl -s -f http://localhost:80 >/dev/null && echo PASS"),
        },
        {
            "name": "Scenario 2: Permission Lockout (HTTP 403 Forbidden)",
            "problem": "Nginx is active, but curl http://localhost:80 returns HTTP 403 Forbidden. Inspect the error logs, determine the permission or ownership issue on the web root files (/var/www/html), fix the permissions, and ensure HTTP 200 is returned.",
            "inject": lambda vm: vm.run_cmd("systemctl restart nginx && chmod 000 /var/www/html/index.nginx-debian.html"),
            "verify": lambda vm: vm.run_cmd('curl -s -o /dev/null -w "%{http_code}" http://localhost:80').strip() == "200",
        },
        {
            "name": "Scenario 3: Corrupted Configuration Syntax",
            "problem": "Nginx failed to start due to a syntax error injected into /etc/nginx/sites-available/default. Run nginx -t to locate the syntax error, remove the invalid line, verify syntax, and start Nginx.",
            "inject": lambda vm: vm.run_cmd("sed -i '/server_name _;/a \\    corrupted_test_directive_xyz;' /etc/nginx/sites-available/default && systemctl stop nginx"),
            "verify": lambda vm: "PASS" in vm.run_cmd("nginx -t && systemctl is-active nginx && curl -s -f http://localhost:80 >/dev/null && echo PASS"),
        },
    ]

    vm = VMController()
    results = []

    try:
        for scen in scenarios:
            res = run_single_trial(scen, vm)
            results.append(res)
    finally:
        vm.stop()

    # Generate Reports
    timestamp = datetime.now(timezone.utc).isoformat()
    passed_count = sum(1 for r in results if r["success"])
    total_scenarios = len(results)
    pass_rate = f"{passed_count}/{total_scenarios} ({round((passed_count/total_scenarios)*100)}%)"

    benchmark_summary = {
        "timestamp": timestamp,
        "model": MODEL_NAME,
        "score": pass_rate,
        "passed": passed_count,
        "total": total_scenarios,
        "scenarios": results,
    }

    # Save JSON
    with open(os.path.join(WORKSPACE_DIR, "benchmark_results.json"), "w") as f:
        json.dump(benchmark_summary, f, indent=2)

    # Save Markdown Scoreboard
    report_md = os.path.join(WORKSPACE_DIR, "REPORT.md")
    with open(report_md, "w") as f:
        f.write("# Autonomous Linux Incident Recovery Benchmark\n\n")
        f.write(f"- **Target Model:** `{MODEL_NAME}`\n")
        f.write(f"- **Benchmark Score:** **{pass_rate}**\n")
        f.write(f"- **Timestamp:** {timestamp}\n\n")
        f.write("## Scoreboard\n\n")
        f.write("| Scenario | Outcome | Duration | Turns |\n")
        f.write("| :--- | :---: | :---: | :---: |\n")
        for r in results:
            badge = "✅ PASSED" if r["success"] else "❌ FAILED"
            f.write(f"| {r['name']} | {badge} | {r['duration_seconds']}s | {r['turns_used']} |\n")
        f.write("\n---\n\n## Detailed Execution Traces\n\n")
        for r in results:
            f.write(f"### {r['name']}\n")
            f.write(f"**Outcome:** {'✅ PASSED' if r['success'] else '❌ FAILED'} ({r['duration_seconds']}s, {r['turns_used']} turns)\n\n")
            for item in r["log"]:
                if item["type"] == "action":
                    f.write(f"**Command:**\n```bash\n{item['cmd']}\n```\n")
                    f.write(f"**Output:**\n```text\n{item['output']}\n```\n\n")
                elif item["type"] == "thought":
                    f.write(f"> {item['text']}\n\n")

    print("\n==================================================")
    print(f"🏁 BENCHMARK COMPLETED: {pass_rate}")
    print(f"Report published to: {report_md}")
    print("==================================================")


if __name__ == "__main__":
    main()
