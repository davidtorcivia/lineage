# Lineage

A local, GPU-rendered art piece for exploring every known direct ancestor of a WikiTree profile.

Views: **Tributaries** (strands through time), **Constellation** (birthplaces on a map, animated through the centuries),
**Tree Rings** (a radial cross-section of the family).

## Run

```sh
python -m http.server 8765    # then open http://localhost:8765/
```

## Data

The app reads `tree.json`, `bios/<Id % 64>.json` and `places.json`, none of which are committed.

1. `python pull.py <WikiTree-ID> <authcode>` pulls ancestors, children, marriages and bios from the WikiTree API.
   Get an authcode by visiting `https://api.wikitree.com/api.php?action=clientLogin&returnURL=http://localhost:8765/authed`
   while the server runs; the code appears in the server log. The session is then kept in `.wt_cookies`, so later runs need only the ID.
   Each step is checkpointed (`raw.json`, `kids.json`, `bios.json`); delete one to redo it.
2. `python geocode.py` geocodes and verifies every place (resumable).
