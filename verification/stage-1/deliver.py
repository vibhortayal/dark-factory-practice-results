#!/usr/bin/env python3
"""Nightshift Verifier - Pocketful stage 1 - delivery/runtime checks (spec §2, §3.1, §3.2, §10).

deliver.py --dir <stage folder> --out <output dir outside the repo> [--tag NAME]

Builds the image from a clean state, starts containers the way the specification
describes, and runs checks.py against a container limited to 2 vCPU / 2 GiB on a
network without outbound access. Writes all output under --out.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RES = []
LOG = None


def log(msg):
    print(msg, flush=True)
    LOG.write(msg + "\n")
    LOG.flush()


def sh(cmd, timeout=900):
    log(f"$ {cmd}")
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    out = (p.stdout + p.stderr).strip()
    if out:
        log("\n".join(out.splitlines()[-25:]))
    return p.returncode, p.stdout.strip()


def rec(cid, clause, row, ok, msg):
    RES.append((cid, ok))
    log(f"[{'PASS' if ok else 'FAIL'}] {cid} ({clause}; rows {row}) {msg}")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def health(base, wait):
    """Seconds until GET /health gives 200 {"status":"ok"}, or None."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < wait:
        try:
            with urllib.request.urlopen(base + "/health", timeout=2) as r:
                if r.status == 200 and json.loads(r.read()) == {"status": "ok"}:
                    return time.monotonic() - t0
        except Exception:
            pass
        time.sleep(0.2)
    return None


def ip_of(name):
    _, out = sh("docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' " + name)
    return out.strip()


def main():
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", default="nsv-stage1")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=False)
    LOG = open(os.path.join(a.out, "deliver.log"), "w")
    tag, net = a.tag, a.tag + "-int"
    names = [f"{tag}-{x}" for x in ("default", "port", "none", "a", "b")]
    sh("docker rm -f " + " ".join(names) + " 2>/dev/null; docker network rm " + net + " 2>/dev/null")

    ok = os.path.isfile(os.path.join(a.dir, "Dockerfile")) and os.path.isfile(os.path.join(a.dir, "RUN.md"))
    rec("A1-files", "§2", "A1", ok, "Dockerfile and RUN.md present in the stage folder")
    rc, _ = sh(f"docker build --no-cache -t {tag} {a.dir}", timeout=1800)
    rec("A1-clean-build", "§2", "A1", rc == 0, "docker build --no-cache from the stage folder")
    if rc != 0:
        return finish(a, names, net)

    # A2/A4: default port 8080, no PORT variable, port mapping, timed start
    hp = free_port()
    sh(f"docker run -d --name {names[0]} --cpus 2 --memory 2g -p 127.0.0.1:{hp}:8080 {tag}")
    secs = health(f"http://127.0.0.1:{hp}", 60)
    rec("A2-default-port", "§3.1, §3.2", "A2,A4", secs is not None,
        f"no PORT set: healthy on mapped 8080 after {secs if secs is None else round(secs, 2)} s (limit 60 s)")
    # A2: PORT variable honoured, reached through a port mapping (so it listens beyond loopback)
    hp2 = free_port()
    sh(f"docker run -d --name {names[1]} --cpus 2 --memory 2g -e PORT=9123 -p 127.0.0.1:{hp2}:9123 {tag}")
    secs = health(f"http://127.0.0.1:{hp2}", 60)
    rec("A2-port-env", "§2, §3.1", "A2,A4", secs is not None,
        f"-e PORT=9123 with mapping: healthy after {secs if secs is None else round(secs, 2)} s")
    dead = health(f"http://127.0.0.1:{hp2}".replace(str(hp2), str(free_port())), 1)
    rec("A2-port-sanity", "§3.1", "A2", dead is None, "an unmapped port does not answer (probe sanity)")
    sh(f"docker rm -f {names[0]} {names[1]}")

    # A3: no network at all - the service must still start and stay up
    sh(f"docker run -d --name {names[2]} --network none --cpus 2 --memory 2g {tag}")
    time.sleep(8)
    _, st = sh("docker inspect -f '{{.State.Running}} {{.State.ExitCode}} {{.State.OOMKilled}}' " + names[2])
    sh(f"docker logs --tail 20 {names[2]}")
    rec("A3-network-none", "§2", "A3", st.startswith("true"), f"container still running after 8 s with --network none (state: {st})")
    sh(f"docker rm -f {names[2]}")

    # A3/A5: full check list against a container on an internal network (no outbound), 2 vCPU / 2 GiB
    sh(f"docker network create --internal {net}")
    sh(f"docker run -d --name {names[3]} --network {net} --cpus 2 --memory 2g {tag}")
    sh(f"docker run -d --name {names[4]} --network {net} --cpus 2 --memory 2g -e PORT=9200 {tag}")
    base, base2 = f"http://{ip_of(names[3])}:8080", f"http://{ip_of(names[4])}:9200"
    s1, s2 = health(base, 60), health(base2, 60)
    isolated = s1 is not None and s2 is not None
    if not isolated:
        log("internal network not reachable from the host; falling back to port-mapped containers on the default bridge")
        sh(f"docker rm -f {names[3]} {names[4]}")
        p1, p2 = free_port(), free_port()
        sh(f"docker run -d --name {names[3]} --cpus 2 --memory 2g -p 127.0.0.1:{p1}:8080 {tag}")
        sh(f"docker run -d --name {names[4]} --cpus 2 --memory 2g -e PORT=9200 -p 127.0.0.1:{p2}:9200 {tag}")
        base, base2 = f"http://127.0.0.1:{p1}", f"http://127.0.0.1:{p2}"
        s1, s2 = health(base, 60), health(base2, 60)
    rec("A4-timed-start", "§2, §3.2", "A4", s1 is not None and s2 is not None,
        f"healthy after {s1} s and {s2} s under --cpus 2 --memory 2g (limit 60 s); isolated network: {isolated}")
    rc, out = sh(f"docker exec {names[3]} sh -c 'wget -T 3 -q -O- http://1.1.1.1 || curl -m 3 -s http://1.1.1.1' ; echo rc=$?")
    log(f"outbound probe from inside the container (informative): {out[-80:]}")
    cmd = (f"{sys.executable} {HERE}/checks.py --base {base} --base2 {base2} "
           f"--kill-cmd 'docker kill {names[3]}' --json {a.out}/checks.json > {a.out}/checks.log 2>&1")
    log(f"$ {cmd}")
    rc = subprocess.run(cmd, shell=True).returncode
    tail = open(os.path.join(a.out, "checks.log")).read().splitlines()
    log("\n".join(l for l in tail if l.startswith("[FAIL]") or l.startswith("    FAIL") or l.startswith("TOTAL")))
    rec("HTTP-check-list", "all", "A5-J6", rc == 0, f"checks.py exit code {rc}; isolated network: {isolated}; see checks.log")
    _, st = sh("docker inspect -f '{{.State.Running}} {{.State.OOMKilled}} {{.RestartCount}}' " + names[4])
    rec("A5-no-oom", "§2 resource limits", "A5", st == "true false 0", f"second container state after the run (running oomkilled restarts): {st}")
    _, st = sh("docker inspect -f '{{.State.OOMKilled}} {{.RestartCount}}' " + names[3])
    rec("A5-no-oom-src", "§2 resource limits", "A5", st == "false 0", f"first container (killed by the cross-container check) oomkilled/restarts: {st}")
    sh(f"docker stats --no-stream --format '{{{{.Name}}}} {{{{.MemUsage}}}} {{{{.CPUPerc}}}}' {names[4]}")
    return finish(a, names, net)


def finish(a, names, net):
    sh("docker rm -f " + " ".join(names) + " 2>/dev/null; docker network rm " + net + " 2>/dev/null")
    bad = [c for c, ok in RES if not ok]
    log(f"\nDELIVERY TOTAL {len(RES)} checks: {len(RES) - len(bad)} passed, {len(bad)} failed {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
