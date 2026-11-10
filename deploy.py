#!/usr/bin/env python3
"""One-command Ghost deployment; standard library only."""
import argparse
import base64
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
HC = "https://api.hetzner.cloud/v1"
CF = "https://api.cloudflare.com/client/v4"

class DeployError(Exception):
    pass

def api(method, url, token, data=None):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, json.dumps(data).encode() if data is not None else None, headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise DeployError(f"{method} {urllib.parse.urlparse(url).path}: HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise DeployError(f"{method} {urllib.parse.urlparse(url).path}: connection failed") from exc
    if result.get("success") is False:
        raise DeployError(f"{method} {urllib.parse.urlparse(url).path}: provider rejected request")
    return result

def env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise DeployError(f"Set {name}")
    return value

def config(args):
    domain = env("GHOST_DOMAIN").lower().rstrip(".")
    if not re.fullmatch(r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain):
        raise DeployError("GHOST_DOMAIN must be a valid public DNS name")
    name = args.name or "ghost-" + domain.replace(".", "-")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,61}[a-z0-9]", name):
        raise DeployError("Invalid server name; use lower-case letters, digits and hyphens")
    result = dict(domain=domain, name=name, server_type=args.server_type, location=args.location,
        htoken=env("HETZNER_TOKEN"), ctoken=env("CLOUDFLARE_TOKEN"), zone=env("CLOUDFLARE_ZONE_ID"), tskey=env("TS_AUTHKEY"))
    if not result["tskey"].startswith("tskey-"):
        raise DeployError("TS_AUTHKEY does not look like a Tailscale auth key")
    return result

def cloud_init(c):
    password = secrets.token_urlsafe(32)
    content = [("/opt/ghost/compose.yaml", (ROOT/"compose.yaml").read_text().replace("__DOMAIN__", c["domain"]).replace("__MYSQL_PASSWORD__", password), "0600"),
               ("/opt/ghost/Caddyfile", (ROOT/"Caddyfile").read_text().replace("__DOMAIN__", c["domain"]), "0644"),
               ("/usr/local/sbin/ghost-bootstrap", (ROOT/"bootstrap.sh").read_text().replace("__TS_AUTHKEY__", c["tskey"]), "0700")]
    files = [{"path": path, "permissions": mode, "encoding": "b64", "content": base64.b64encode(body.encode()).decode()} for path,body,mode in content]
    return "#cloud-config\n" + json.dumps({"package_update": True, "write_files": files, "runcmd": [["/usr/local/sbin/ghost-bootstrap"]]})

def named(kind, name, token):
    data = api("GET", f"{HC}/{kind}?name={urllib.parse.quote(name)}", token)
    return next((x for x in data[kind] if x["name"] == name), None)

def firewall(c):
    name = c["name"] + "-web-only"
    found = named("firewalls", name, c["htoken"])
    if found:
        rules = {(r.get("direction"), r.get("protocol"), r.get("port")) for r in found["rules"]}
        if rules != {("in", "tcp", "80"), ("in", "tcp", "443")}:
            raise DeployError("Existing firewall has unexpected rules; inspect it before reuse")
        return found["id"]
    rules = [{"direction":"in", "protocol":"tcp", "port":p, "source_ips":["0.0.0.0/0","::/0"]} for p in ("80","443")]
    return api("POST", HC+"/firewalls", c["htoken"], {"name":name,"rules":rules})["firewall"]["id"]

def wait_action(action_id, token):
    for _ in range(60):
        action = api("GET", f"{HC}/actions/{action_id}", token)["action"]
        if action["status"] == "success": return
        if action["status"] == "error": raise DeployError(f"Hetzner action failed: {action.get('error', {}).get('code', 'unknown')}")
        time.sleep(5)
    raise DeployError("Hetzner action timed out")

def server(c, firewall_id):
    found = named("servers", c["name"], c["htoken"])
    if found:
        if firewall_id not in {f["id"] for f in found.get("firewalls", [])}:
            raise DeployError("Existing server lacks expected firewall; refusing reuse")
        return found
    body = {"name":c["name"],"server_type":c["server_type"],"location":c["location"],"image":"ubuntu-24.04",
        "firewalls":[{"firewall":firewall_id}],"user_data":cloud_init(c),"labels":{"managed-by":"ghost-hetzner-deploy"}}
    result = api("POST", HC+"/servers", c["htoken"], body)
    wait_action(result["action"]["id"], c["htoken"])
    return api("GET", f"{HC}/servers/{result['server']['id']}", c["htoken"])["server"]

def dns(c, ip):
    base = f"{CF}/zones/{c['zone']}/dns_records"
    query = urllib.parse.urlencode({"type":"A","name":c["domain"]})
    records = api("GET", base+"?"+query, c["ctoken"])["result"]
    if len(records)>1: raise DeployError("Multiple A records exist; resolve manually")
    body = {"type":"A","name":c["domain"],"content":ip,"proxied":False,"ttl":60}
    if records:
        if records[0]["content"] == ip and records[0].get("proxied") is False: return
        if os.environ.get("GHOST_ALLOW_DNS_REPLACE") != "yes":
            raise DeployError("Existing A record differs; set GHOST_ALLOW_DNS_REPLACE=yes to replace it")
        api("PATCH", base+"/"+records[0]["id"], c["ctoken"], body)
    else:
        api("POST", base, c["ctoken"], body)

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-type", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--name")
    c = config(parser.parse_args(argv))
    machine = server(c, firewall(c))
    ip = machine["public_net"]["ipv4"]["ip"]
    dns(c, ip)
    print(f"VPS: {c['name']} ({ip}); Ghost: https://{c['domain']}")
    print("Cloud-init and HTTPS issuance may take several minutes; inspect cloud-init logs through Tailscale if needed.")
    print("SSH is reachable only through your Tailscale policy. Public TCP/22 is blocked by the Hetzner firewall.")

if __name__ == "__main__":
    try: main()
    except DeployError as exc:
        print(f"Deployment stopped: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
