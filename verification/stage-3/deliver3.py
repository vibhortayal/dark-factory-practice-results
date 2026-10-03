#!/usr/bin/env python3
"""Nightshift Verifier - Pocketful stage 3 - delivery run.

deliver3.py --repo <result repo> --out <dir outside the repo> --pw-python <python with playwright>

Builds stage-2 (clean) and stage-1, repeats the stage-1 delivery checks for stage-2, runs checks2.py
(stage-1 list + stage-2 API list) and ui.py against containers limited to 2 vCPU / 2 GiB on a docker
network without outbound access.
"""
import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "stage-1"))
HERE = os.path.dirname(os.path.abspath(__file__))
import deliver as d  # noqa: E402  (stage-1 helpers: sh, rec, health, ip_of, free_port, log)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pw-python", required=True)
    ap.add_argument("--stage1-rev", default="172a3180c731a310e00e403ea1c4990a4a78b5d4")
    ap.add_argument("--stage2-rev", default="c59be33b9aaed102d1728cf7f6d9df7a2e0f571f")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=False)
    d.LOG = open(os.path.join(a.out, "deliver.log"), "w")
    sh, rec, log = d.sh, d.rec, d.log
    tag, tag1, tag2, net = "nsv-stage3", "nsv-stage3-s1", "nsv-stage3-s2", "nsv-stage3-int"
    names = [f"{tag}-{x}" for x in ("default", "port", "none", "a", "b", "ui", "s1", "s2")]
    clean = "docker rm -f " + " ".join(names) + " 2>/dev/null; docker network rm " + net + " 2>/dev/null"
    sh(clean)
    s2, s1, s2old = os.path.join(a.repo, "stage-3"), os.path.join(a.repo, "stage-1"), os.path.join(a.repo, "stage-2")

    rc, out = sh(f"git -C {a.repo} diff --stat {a.stage1_rev} -- stage-1 | wc -l")
    rec("V3-stage1-unchanged", "task (one folder per stage)", "V3", out.strip() == "0", f"git diff {a.stage1_rev[:8]} -- stage-1 is empty")
    rc, out = sh(f"git -C {a.repo} diff --stat {a.stage2_rev} -- stage-2 | wc -l")
    rec("V3-stage2-unchanged", "task (one folder per stage)", "V3", out.strip() == "0", f"git diff {a.stage2_rev[:8]} -- stage-2 is empty")
    ok = os.path.isfile(os.path.join(s2, "Dockerfile")) and os.path.isfile(os.path.join(s2, "RUN.md"))
    rec("A1-files", "§2", "K2,A1", ok, "stage-3 has its own Dockerfile and RUN.md")
    rc, _ = sh(f"docker build --no-cache -t {tag} {s2}", timeout=1800)
    rec("A1-clean-build", "§2", "K2,A1", rc == 0, "docker build --no-cache of stage-3")
    rc1, _ = sh(f"docker build -t {tag1} {s1}", timeout=1800)
    rc2, _ = sh(f"docker build -t {tag2} {s2old}", timeout=1800)
    rc1 = rc1 or rc2
    rec("S1-S2-build", "upgrade", "AB1", rc1 == 0, "docker build of stage-1 and stage-2 (sources of the upgrade exports)")
    if rc != 0 or rc1 != 0:
        return finish(sh, log, clean)

    hp = d.free_port()
    sh(f"docker run -d --name {names[0]} --cpus 2 --memory 2g -p 127.0.0.1:{hp}:8080 {tag}")
    secs = d.health(f"http://127.0.0.1:{hp}", 60)
    rec("A2-default-port", "§3.1, §3.2", "K1,A2,A4", secs is not None, f"no PORT set: healthy on mapped 8080 after {secs} s")
    hp2 = d.free_port()
    sh(f"docker run -d --name {names[1]} --cpus 2 --memory 2g -e PORT=9123 -p 127.0.0.1:{hp2}:9123 {tag}")
    secs = d.health(f"http://127.0.0.1:{hp2}", 60)
    rec("A2-port-env", "§2, §3.1", "K1,A2,A4", secs is not None, f"-e PORT=9123 with mapping: healthy after {secs} s")
    sh(f"docker rm -f {names[0]} {names[1]}")
    sh(f"docker run -d --name {names[2]} --network none --cpus 2 --memory 2g {tag}")
    time.sleep(8)
    _, st = sh("docker inspect -f '{{.State.Running}} {{.State.ExitCode}} {{.State.OOMKilled}}' " + names[2])
    rec("A3-network-none", "§2", "K2,A3", st.startswith("true"), f"container running after 8 s with --network none ({st})")
    sh(f"docker rm -f {names[2]}")

    sh(f"docker network create --internal {net}")
    lim = f"--network {net} --cpus 2 --memory 2g"
    sh(f"docker run -d --name {names[3]} {lim} {tag}")
    sh(f"docker run -d --name {names[4]} {lim} -e PORT=9200 {tag}")
    sh(f"docker run -d --name {names[5]} {lim} {tag}")
    sh(f"docker run -d --name {names[6]} {lim} {tag1}")
    sh(f"docker run -d --name {names[7]} {lim} {tag2}")
    base, base2 = f"http://{d.ip_of(names[3])}:8080", f"http://{d.ip_of(names[4])}:9200"
    baseui, bases1 = f"http://{d.ip_of(names[5])}:8080", f"http://{d.ip_of(names[6])}:8080"
    bases2 = f"http://{d.ip_of(names[7])}:8080"
    hs = [d.health(b, 60) for b in (base, base2, baseui, bases1, bases2)]
    rec("A4-timed-start", "§2, §3.2", "K5,A4", all(h is not None for h in hs), f"healthy after {hs} s under --cpus 2 --memory 2g on an internal network")
    if not all(h is not None for h in hs):
        return finish(sh, log, clean)

    cmd = (f"cd {HERE} && S1BASE={bases1} S2BASE={bases2} S3B={baseui} {sys.executable} checks3.py --base {base} --base2 {base2} "
           f"--kill-cmd 'docker kill {names[3]}' --json {a.out}/checks.json > {a.out}/checks.log 2>&1")
    log(f"$ {cmd}")
    rc = subprocess.run(cmd, shell=True).returncode
    lines = open(os.path.join(a.out, "checks.log")).read().splitlines()
    log("\n".join(l for l in lines if l.startswith("[FAIL]") or l.startswith("    FAIL") or l.startswith("TOTAL")))
    rec("API-check-list", "stage-1 + stage-2", "K1,L2,R1,R5,S,T", rc == 0, f"checks3.py exit code {rc}; see checks.log")

    cmd = (f"cd {HERE} && {a.pw_python} ui.py --base {baseui} --s1base {bases1} --out {a.out}/ui > {a.out}/ui.log 2>&1")
    log(f"$ {cmd}")
    rc = subprocess.run(cmd, shell=True).returncode
    lines = open(os.path.join(a.out, "ui.log")).read().splitlines()
    log("\n".join(l for l in lines if l.startswith("[FAIL]") or l.startswith("    FAIL") or l.startswith("UI TOTAL")))
    rec("UI-check-list", "stage-2 UI", "L-R,U", rc == 0, f"ui.py exit code {rc}; see ui.log")

    for n in (names[4], names[5]):
        _, st = sh("docker inspect -f '{{.State.Running}} {{.State.OOMKilled}} {{.RestartCount}}' " + n)
        rec("A5-no-oom-" + n[-2:], "§2 resource limits", "K5,A5", st == "true false 0", f"{n} after the run (running oomkilled restarts): {st}")
    sh(f"docker stats --no-stream --format '{{{{.Name}}}} {{{{.MemUsage}}}}' {names[4]} {names[5]}")
    return finish(sh, log, clean)


def finish(sh, log, clean):
    sh(clean)
    bad = [c for c, ok in d.RES if not ok]
    log(f"\nDELIVERY TOTAL {len(d.RES)} checks: {len(d.RES) - len(bad)} passed, {len(bad)} failed {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
