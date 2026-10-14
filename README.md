# CampConditions.au — Victoria MVP
- Build: `python3 scripts/build.py` (stdlib only, ~40 s) → `dist/`
- Test: `python3 scripts/test.py` (internal links, JSON-LD, sitemap)
- Preview: `python3 -m http.server 8080 -d dist` → http://localhost:8080
Deploy target: Cloudflare Pages (free, commercial use OK); rebuild via GitHub Actions cron every 3 h.

## CI / deploy
`.github/workflows/build-deploy.yml` builds and tests every 3 hours, on push and on demand, and uploads `dist/` as an artefact.
Deployment to Cloudflare Pages runs **only** once repo secrets `CLOUDFLARE_API_TOKEN` (Pages:Edit) and `CLOUDFLARE_ACCOUNT_ID` are added; until then it is skipped.
`dist/` is not committed (see `.gitignore`).
