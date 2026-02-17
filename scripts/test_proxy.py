"""Quick test: compare direct Plex responses vs proxy responses."""
import httpx
import os

token = os.environ["PLEX_TOKEN"]
plex_url = os.environ.get("PLEX_URL", "http://localhost:32400")
headers = {"X-Plex-Token": token, "Accept": "application/json"}

# Direct from Plex
r1 = httpx.get(plex_url + "/library/metadata/12787/allLeaves", headers=headers)
eps_direct = r1.json().get("MediaContainer", {}).get("Metadata", [])[:3]

# Through proxy
r2 = httpx.get("http://localhost:32401/library/metadata/12787/allLeaves", headers=headers)
eps_proxy = r2.json().get("MediaContainer", {}).get("Metadata", [])[:3]

print("=== DIRECT (Plex :32400) ===")
for ep in eps_direct:
    s = ep.get("parentIndex", "?")
    e = ep.get("index", "?")
    t = ep.get("title", "N/A")
    print("  S{}E{} - {}".format(s, e, t))

print()
print("=== THROUGH PROXY (:32401) ===")
for ep in eps_proxy:
    s = ep.get("parentIndex", "?")
    e = ep.get("index", "?")
    t = ep.get("title", "N/A")
    print("  S{}E{} - {}".format(s, e, t))
