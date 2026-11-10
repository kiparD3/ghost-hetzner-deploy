import argparse
import base64
import json
import os
import unittest
from unittest.mock import patch

import deploy

CONFIG = {"domain":"blog.example.com","name":"ghost-blog-example-com","server_type":"cpx22","location":"fsn1","htoken":"h","ctoken":"c","zone":"z","tskey":"tskey-auth-example"}

class DeployTests(unittest.TestCase):
    def test_config_requires_valid_domain_and_secrets(self):
        values={"GHOST_DOMAIN":"blog.example.com","HETZNER_TOKEN":"h","CLOUDFLARE_TOKEN":"c","CLOUDFLARE_ZONE_ID":"z","TS_AUTHKEY":"tskey-auth-example"}
        with patch.dict(os.environ, values, clear=True):
            c=deploy.config(argparse.Namespace(name=None,server_type="cpx22",location="fsn1"))
            self.assertEqual(c["name"],CONFIG["name"])
            os.environ["GHOST_DOMAIN"]="invalid/name"
            with self.assertRaises(deploy.DeployError): deploy.config(argparse.Namespace(name=None,server_type="cpx22",location="fsn1"))
    def test_cloud_init_has_private_services_and_no_public_ssh(self):
        cloud=deploy.cloud_init(CONFIG)
        obj=json.loads(cloud.split("\n",1)[1])
        files={f["path"]:base64.b64decode(f["content"]).decode() for f in obj["write_files"]}
        self.assertEqual(obj["runcmd"],[["/usr/local/sbin/ghost-bootstrap"]])
        self.assertIn("tskey-auth-example",files["/usr/local/sbin/ghost-bootstrap"])
        self.assertIn("https://blog.example.com",files["/opt/ghost/compose.yaml"])
        self.assertNotIn("22:22",files["/opt/ghost/compose.yaml"])
        self.assertEqual(obj["write_files"][0]["permissions"],"0600")
    @patch("deploy.api")
    def test_firewall_allows_only_web_ports(self, api):
        api.side_effect=[{"firewalls":[]},{"firewall":{"id":7}}]
        self.assertEqual(deploy.firewall(CONFIG),7)
        rules=api.call_args.args[3]["rules"]
        self.assertEqual({r["port"] for r in rules},{"80","443"})
        self.assertTrue(all(r["direction"]=="in" for r in rules))
    @patch("deploy.api")
    def test_existing_server_without_firewall_is_rejected(self, api):
        api.return_value={"servers":[{"name":CONFIG["name"],"firewalls":[]}]}
        with self.assertRaises(deploy.DeployError):deploy.server(CONFIG,7)
    @patch("deploy.api")
    def test_existing_dns_requires_explicit_replace(self, api):
        api.return_value={"result":[{"id":"id","content":"192.0.2.1","proxied":False}]}
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(deploy.DeployError):deploy.dns(CONFIG,"198.51.100.2")
        self.assertEqual(api.call_count,1)
    @patch("deploy.api")
    def test_new_dns_record_is_unproxied(self, api):
        api.return_value={"result":[]}
        deploy.dns(CONFIG,"198.51.100.2")
        self.assertEqual(api.call_args.args[3]["proxied"],False)
    @patch("deploy.api")
    def test_failed_hetzner_action_stops(self, api):
        api.return_value={"action":{"status":"error","error":{"code":"quota_exceeded"}}}
        with self.assertRaisesRegex(deploy.DeployError,"quota_exceeded"):deploy.wait_action(1,"token")

    @patch("deploy.urllib.request.urlopen")
    @patch("deploy.socket.getaddrinfo")
    def test_blog_is_ready_only_after_dns_and_https(self, lookup, open_url):
        lookup.return_value=[(None,None,None,None,("198.51.100.2",443))]
        open_url.return_value.__enter__.return_value.status=200
        deploy.wait_for_blog("blog.example.com","198.51.100.2",timeout=1)
        open_url.assert_called_once_with("https://blog.example.com/",timeout=10)

    @patch("deploy.time.sleep")
    @patch("deploy.time.monotonic")
    @patch("deploy.socket.getaddrinfo")
    def test_blog_readiness_times_out_without_expected_dns(self, lookup, clock, sleep):
        clock.side_effect=[0,0,2]
        lookup.return_value=[(None,None,None,None,("198.51.100.3",443))]
        with self.assertRaisesRegex(deploy.DeployError,"did not become healthy"):
            deploy.wait_for_blog("blog.example.com","198.51.100.2",timeout=1,interval=0)
        sleep.assert_called_once_with(0)

if __name__=="__main__":unittest.main()
