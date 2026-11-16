# CampConditions.au — Victoria MVP
- Build: `python3 scripts/build.py` (stdlib only, ~40 s) → `dist/`
- Test: `python3 scripts/test.py` (internal links, JSON-LD, sitemap)
- Preview: `python3 -m http.server 8080 -d dist` → http://localhost:8080
Deploy target: Cloudflare Pages (free, commercial use OK); rebuild via GitHub Actions cron every 3 h.

## CI / deploy
`.github/workflows/build-deploy.yml` builds and tests every 3 hours, on push and on demand, and uploads `dist/` as an artefact.
Deployment to Cloudflare Pages runs **only** once repo secrets `CLOUDFLARE_API_TOKEN` (Pages:Edit) and `CLOUDFLARE_ACCOUNT_ID` are added; until then it is skipped.
`dist/` is not committed (see `.gitignore`).

## Trip Check waitlist

`/trip-check/` is a waitlist page. Nothing else on the site links to it. Joining sends one confirmation email through Resend's transactional send API (`POST /emails`) and, after the link is opened, stores the address in Workers KV under `TRIPCHECK_KV`. The handlers do not create or change Resend contacts, segments, topics or audiences, and they do not read the digest one-list flag.

Do not add a root `wrangler.toml` until the namespace id is real. `wrangler pages deploy` treats that file as the source of truth for the Pages project and can replace the dashboard bindings this site already uses. `config/trip-check.wrangler.toml.example` is notes only. Wrangler does not load it.

Before a confirmation can be saved in production:

1. Create a Workers KV namespace. Dashboard: Workers & Pages → KV → Create. Or `npx wrangler kv namespace create TRIPCHECK_KV`. Keep the namespace id.
2. Bind that namespace on the `campconditions` Pages project for production. Variable name: `TRIPCHECK_KV`. Dashboard: Workers & Pages → campconditions → Settings → Bindings → Add → KV namespace → select the namespace. Redeploy after the binding is saved. The code reads `env.TRIPCHECK_KV`.
3. Optionally set `TRIPCHECK_ADMIN_KEY` (Settings → Variables and Secrets → Add → Encrypt, or `npx wrangler pages secret put TRIPCHECK_ADMIN_KEY --project-name=campconditions`). `GET /api/trip-check-count` with header `X-Tripcheck-Key` set to that secret returns `{"confirmed":N}` and no email addresses. If the secret is unset, the count stays closed.
4. Optional `TRIPCHECK_SECRET` signs the confirmation link. If it is unset, the link uses the existing `CONFIRM_SECRET`. Sending uses the existing `RESEND_API_KEY` and `FROM_EMAIL`. `SITE_URL` is used for the link when it is set.

Until `TRIPCHECK_KV` is bound, the form says the waitlist is not available and does not send mail.
