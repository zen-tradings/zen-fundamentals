# zen-newsletter-agent

An agent that curates content and generates a newsletter.

## Basic Structure Design

> Draft — to be refined as the project grows.

```
zen-newsletter-agent/
├── README.md          # this file
├── main.py            # entry point: run the agent
├── agent.py           # core agent logic (collect → curate → write)
└── config.py          # settings: sources, schedule, recipients
```

## Workflow (rough idea)

1. **Collect** — fetch content from sources (RSS, web, APIs)
2. **Curate** — agent picks the most relevant items
3. **Write** — agent drafts the newsletter content
4. **Send** — deliver via email

## TODO

- [ ] Decide on LLM/agent framework
- [ ] Define content sources
- [ ] Choose email delivery method
