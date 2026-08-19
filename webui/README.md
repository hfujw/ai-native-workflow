# Lumen WebUI

This is the Lumen workspace's WebUI — a React 18 + Vite + TypeScript + Tailwind frontend
(task 13/14). It talks to the Lumen backend (FastAPI, port 8001) over `/v1/responses` SSE
and the `/api` REST surface, and renders the deep-loop output: **thinking blocks + tool
cards**, **finished-artifact previews**, and the **work gallery**.

> Project overview, architecture, and run instructions: root [`README.md`](../README.md).
> Frontend integration notes: [`docs/TASK13_接后端规划.md`](../docs/TASK13_接后端规划.md).

## Run (dev)

```bash
cd webui
npm install
npm run dev          # http://127.0.0.1:5173
```

Vite proxies `/v1`, `/api`, `/webui`, `/works` to `http://127.0.0.1:8001` (the backend).
Real generation needs a DeepSeek key: set `DEEPSEEK_API_KEY` in `backend/.env`, or enter it
in the frontend **设置 → 模型** (stored in localStorage, sent as `Authorization`).

## How it connects

- `src/hooks/useLumenStream.ts` — the message-stream hook: `send` → POST `/v1/responses`
  (SSE). Structured events (`lumen.reasoning.delta` → thinking block, `lumen.tool` →
  tool card) feed the thread-projection pipeline.
- `src/lib/lumen-client.ts` — **LumenClient**: event emitter + run lifecycle
  (beginRun / endRun / canReconcileCanonicalCompletion), the client shim that replaced
  the old WS client.
- `src/lib/lumen-api.ts` — maps `/api/history` for the chat list / gallery.
- `src/lib/lumen-key.ts` — DeepSeek key + search-service credentials in localStorage.
- `src/components/ArtifactCard.tsx` — finished-HTML preview (`/works/{id}` iframe).
- `src/components/GalleryView.tsx` — work gallery (click a card to re-open the chat).

## Test

```bash
cd webui
npx vitest run
```

## Build

```bash
cd webui
npm run build        # → dist/
```

## Acknowledgements

- [`agent-chat-ui`](https://github.com/langchain-ai/agent-chat-ui) for UI and interaction
  inspiration across the chat surface.
