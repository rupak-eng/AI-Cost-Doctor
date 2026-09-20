# AI Cost Doctor

> **Find where your AI budget is leaking.**

Connect your AI stack. Discover what's driving your LLM spend, why costs changed,
and exactly where you can save.

AI Cost Doctor helps US/UK AI startups and SaaS companies understand, diagnose,
and reduce their LLM/AI infrastructure spending. It answers
**"What should I do about my AI bill?"** — not just "What happened to my AI bill?"

## Status

🚧 **Phase 0** — market research & competitor analysis in progress.

## Repository structure

| Path        | Contents                                              |
| ----------- | ----------------------------------------------------- |
| `research/` | Market research, competitor analysis, wedge decision  |
| `specs/`    | Product specification & architecture documents        |
| `app/`      | Application source code (web SaaS MVP)                |

## Planned tech stack

- **Frontend:** Next.js, TypeScript, Tailwind CSS
- **Backend:** Python, FastAPI, PostgreSQL
- **Infra:** Docker, AWS-compatible deployment

## Principles

- Actionable cost diagnosis over generic observability dashboards.
- Deterministic cost calculations — LLMs only for diagnosis and explanation.
- Never fake integrations or analytics; demo data is always labeled as demo.
- Security-first: encrypted secrets, tenant isolation, audit logging.
