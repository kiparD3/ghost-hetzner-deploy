# Ghost on Hetzner, with private SSH

This is a **separate project** from `fullstack-roles-task`. `deploy.py` provisions a Hetzner Cloud VPS, attaches a firewall allowing only public HTTP/HTTPS, joins the server to Tailscale for SSH, starts Ghost/MySQL/Caddy with Docker Compose, and creates a Cloudflare DNS A record. It uses Python's standard library; no new package is needed on the computer running the script. The VPS incurs Hetzner charges when deployed.

## Before you run it

You need a Hetzner Cloud API token with server/firewall write access, a Cloudflare zone and token with DNS edit access, and a Tailscale tailnet with an SSH policy allowing your own device/user to reach the server. Use a **tagged, short-lived** Tailscale auth key. The domain must be in the Cloudflare zone. Choose a currently available Hetzner server type/location; check its price before deployment. You also need Python 3.11+ locally.

Set these environment variables in your shell or an untracked `.env` you source yourself:

```bash
export HETZNER_TOKEN='...'
export CLOUDFLARE_TOKEN='...'
export CLOUDFLARE_ZONE_ID='...'
export TS_AUTHKEY='tskey-...'
export GHOST_DOMAIN='blog.example.com'
python3 deploy.py --server-type cpx22 --location fsn1
```

These are example server type/location values, not a price or availability promise. The script does not ask before creating billable resources; the command above is the deployment action. Do not commit tokens. It writes the Tailscale key into Hetzner cloud-init user-data so the first boot can join the tailnet; Hetzner project administrators can read that user-data. Revoke/rotate the key after first join. A database password is generated per new server and stored in the server's root-only Compose file and Hetzner user-data.

The script will refuse to reuse a same-named server without its expected firewall and will refuse to replace a different DNS A record unless `GHOST_ALLOW_DNS_REPLACE=yes`. Reruns of an already provisioned name reuse the server rather than create another. They do **not** reapply changed bootstrap files to that server.

The blog is public on HTTPS. Public TCP/22 is excluded from the Hetzner firewall; SSH access uses Tailscale SSH and your tailnet policy. Only HTTP/HTTPS is exposed in the Docker stack. Check your tailnet SSH policy before deployment so you do not lock yourself out; Hetzner's web console is the recovery path.

Initial provisioning finishes before DNS propagation and automatic HTTPS issuance may finish. Inspect the returned URL after a few minutes. Ghost starts with a persistent MySQL 8 database and content volumes. Configure backups, SMTP/email delivery, updates, monitoring and Ghost's initial `/ghost/` owner setup before using the blog for real publishing. This prototype does not configure those operational services.

## Local checks

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile deploy.py
bash -n bootstrap.sh
```

These mock provider calls; they do not create a VPS. There is no live deployment in this repository yet.

## Sources

- [Hetzner Cloud API and firewall rules](https://docs.hetzner.cloud/reference/cloud)
- [Tailscale server setup and SSH](https://tailscale.com/docs/how-to/set-up-servers)
- [Ghost Docker installation](https://ghost.org/docs/install/docker/)
- [Cloudflare DNS record API](https://developers.cloudflare.com/api/resources/dns/subresources/records/methods/create/)
