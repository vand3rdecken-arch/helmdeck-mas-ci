# -*- coding: utf-8 -*-
"""One-shot Plane provisioning - run once after `docker compose up` and the
whole thing works with zero clicking: instance admin + user, workspace,
project (repo preset), personal API token -> written into settings.json so
the bridge starts on the next `swarm.py serve`.

  python plane_setup.py [email] [password]

Defaults: owner@swarmdeck.local / a generated strong password (printed and
saved to plane_credentials.txt - change it later in Plane if you care)."""
import json, os, sys, time
import urllib.request, urllib.parse, urllib.error
from http.cookiejar import CookieJar

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = "http://localhost:8090"

jar = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

def req(path, data=None, form=False, method=None):
    url = BASE + path
    headers = {}
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
    csrf = next((c.value for c in jar if c.name == "csrftoken"), None)
    if csrf:
        headers["X-CSRFToken"] = csrf
        headers["Referer"] = BASE + "/"
    r = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with opener.open(r, timeout=60) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw or b"{}")
            except ValueError:
                return resp.status, {"raw": raw[:200].decode("utf-8", "replace"),
                                     "url": resp.geturl()}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except ValueError:
            return e.code, {"raw": raw[:300].decode("utf-8", "replace")}

def main():
    email = sys.argv[1] if len(sys.argv) > 1 else "owner@swarmdeck.local"
    if len(sys.argv) > 2:
        password = sys.argv[2]
    else:
        import secrets
        password = "Sd!" + secrets.token_urlsafe(14)

    # wait for the API to answer
    for i in range(60):
        try:
            code, d = req("/auth/get-csrf-token/")
            if code == 200:
                break
        except Exception:
            pass
        print("waiting for plane api... (%d)" % i)
        time.sleep(5)
    else:
        sys.exit("plane API never came up on " + BASE)

    # instance admin sign-up (also signs us in). Form POST, redirects on error.
    csrf = next((c.value for c in jar if c.name == "csrftoken"), "")
    code, d = req("/api/instances/admins/sign-up/",
                  {"email": email, "password": password, "first_name": "Owner",
                   "company_name": "SwarmDeck", "is_telemetry_enabled": "False",
                   "csrfmiddlewaretoken": csrf}, form=True)
    landed = d.get("url", d.get("raw", ""))
    if "ADMIN_ALREADY_EXIST" in str(d) or "USER_ALREADY_EXIST" in str(d):
        print("admin exists - signing in instead")
        req("/auth/get-csrf-token/")
        csrf = next((c.value for c in jar if c.name == "csrftoken"), "")
        code, d = req("/auth/sign-in/",
                      {"email": email, "password": password,
                       "csrfmiddlewaretoken": csrf}, form=True)
        if "error_code" in str(d):
            sys.exit("sign-in failed (wrong stored password?): " + str(d)[:200])
    elif "error_code" in str(landed):
        sys.exit("admin sign-up failed: " + str(landed)[:300])
    print("signed in as", email)

    code, me = req("/api/users/me/")
    if code != 200:
        sys.exit("session not established: %s %s" % (code, str(me)[:200]))

    # mark onboarding done so the web UI doesn't trap you in a wizard
    req("/api/users/me/", {"is_onboarded": True}, method="PATCH")
    req("/api/users/me/onboard/",
        {"onboarding_step": {"workspace_join": True, "profile_complete": True,
                             "workspace_create": True, "workspace_invite": True}},
        method="PATCH")

    # workspace
    code, ws = req("/api/workspaces/")
    slugs = [w.get("slug") for w in ws] if isinstance(ws, list) else []
    if slugs:
        slug = slugs[0]
        print("workspace exists:", slug)
    else:
        code, w = req("/api/workspaces/", {"name": "SwarmDeck", "slug": "swarmdeck",
                                           "organization_size": "Just myself"})
        if code not in (200, 201):
            sys.exit("workspace create failed: " + str(w)[:300])
        slug = w["slug"]
        print("workspace created:", slug)

    # project with repo preset
    code, projects = req("/api/workspaces/%s/projects/" % slug)
    have = {p.get("name") for p in projects} if isinstance(projects, list) else set()
    if "SwarmDeck" not in have:
        code, pr = req("/api/workspaces/%s/projects/" % slug,
                       {"name": "SwarmDeck", "identifier": "SWARM", "network": 2})
        if code not in (200, 201):
            sys.exit("project create failed: " + str(pr)[:300])
        print("project created: SwarmDeck (SWARM)")
    else:
        print("project exists: SwarmDeck")

    # personal API token for the bridge
    code, tok = req("/api/users/api-tokens/", {"label": "swarmdeck-bridge"})
    token = tok.get("token")
    if not token:
        sys.exit("api token create failed: " + str(tok)[:300])
    print("api token created")

    # write everything into settings.json - the bridge picks it up on serve
    sys.path.insert(0, ROOT)
    import events
    repo = events.settings().get("default_repo") or os.path.abspath(os.path.join(ROOT, ".."))
    events.save_settings({"plane": {"base": BASE, "api_token": token,
                                    "workspace": slug,
                                    "repos": {"SwarmDeck": repo},
                                    "default_repo": repo, "poll_secs": 20}})
    with open(os.path.join(ROOT, "plane_credentials.txt"), "w") as f:
        f.write("plane %s\n%s\n%s\n" % (BASE, email, password))
    print("\nDONE. Plane: %s  (login %s / password in plane_credentials.txt)" % (BASE, email))
    print("Project 'SwarmDeck' is preset to repo: %s" % repo)
    print("Restart the daemon (swarm.py serve) and the bridge goes live.")

if __name__ == "__main__":
    main()
