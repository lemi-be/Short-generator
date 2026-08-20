# Vendored: FreeCut

This directory is a **fully-owned fork** of the FreeCut browser video editor,
pinned and committed into this repository. It is the only editor used by the
Django web UI; the legacy ffmpeg-based trimmer has been removed.

## Upstream

- Project: https://github.com/walterlow/freecut
- License: MIT
- Pinned commit: `4d62e8082c5eb387a96275bcbd323d28f6e41a62`
- Vendored on: 2026-08-11

## Upstream decoupling (important)

This fork is intentionally **not** a git submodule and has **no remote**:

- `.git/` and `.gitmodules` were deleted after cloning.
- There is no `git fetch` / auto-update mechanism.
- Upstream GitHub changes can never affect this project by accident.
- To upgrade deliberately, vendor a new snapshot by hand and re-apply the
  patches below.

## Layout

- `src/` – FreeCut source (patched, see below)
- `dist/` – committed production build (Vite build output). Committed so the
  runtime needs **no Node.js and no network**. `dist/` was excluded from
  `.gitignore` for this reason.
- `node_modules/` – NOT committed (only needed for the one-time build).

## Building

Requires Node 22+ and npm. From this directory:

```powershell
npm ci
npm run build
```

The result lands in `dist/`. Runtime browser requirement: Chrome/Edge 113+
(WebGPU + WebCodecs) with cross-origin isolation headers (COOP/COEP) served
by the Django app.

## Our fork patches (base/URL + build config only)

1. `vite.config.ts` – `base: '/editor/'`, `sourcemap: false`.
2. `src/app.tsx` – TanStack Router `basepath: '/editor'`.
3. `src/main.tsx` – service-worker registration and the update-check fetch
   use `import.meta.env.BASE_URL` so they resolve under `/editor/`.
4. `src/routes/index.tsx` – landing-page assets rewritten to
   `${import.meta.env.BASE_URL}assets/landing/*`.
5. `src/features/workspace-gate/workspace-gate-splash.tsx` and
   `src/features/editor/components/toolbar.tsx` – `/docs*` anchors rewritten
   with `import.meta.env.BASE_URL`.

No editor features were changed. The Django app serves `dist/` at `/editor/`.
