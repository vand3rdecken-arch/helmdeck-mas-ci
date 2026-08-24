# Mint a pairing deep link for the sandbox daemon (same payload the owner UI
# builds: /surfaces/relay/pair = relay_client.pairing_payload + a fresh device token).
#   py -3.12 .smoke/pair_link.py
# Prints helmdeck://pair?c=<b64url{u,r,k,t}> - feed it to the emulator via
#   adb shell am start -a android.intent.action.VIEW -d "<link>"
import base64
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "daemon"))
import auth
import relay_client

pay = relay_client.pairing_payload()
tok = auth.issue_token("owner", "phone (smoke)")
code = base64.urlsafe_b64encode(json.dumps(
    {"u": pay["url"], "r": pay["room"], "k": pay["daemon_pub"], "t": tok}
).encode()).decode().rstrip("=")
print("helmdeck://pair?c=" + code)
