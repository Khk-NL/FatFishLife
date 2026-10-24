# QQ command reference

Use `/help` for the overview and `<command> help` for details. Daily conversation and ordinary result messages remain Chinese. Existing Chinese aliases still work; the default help shows English names only.

| Command | Purpose | Common actions |
| --- | --- | --- |
| `/memory` | This conversation's memory | `status`, `recent`, `search`, `add`, `public`, `summary`, `journal`, `distill`, `persona`, `import`, `bind` |
| `/lore` | Public Arknights sources and graph | `status`, `list`, `sync`, `query` |
| `/style` | Group expression learning | `status`, `samples`, `learn`, `like`, `dislike` |
| `/offline` | Work schedule and manual mode | `status`, `on`, `off`, `auto` |
| `/cost` | Recorded 24-hour usage and estimated cost | No arguments; owner private chat |
| `/life` | Daily reflection and public drafts | `status`, `diary`, `growth`, `draft`, `preview`, `resume` |
| `/video` | Updream brief and export review | `topics`, `create`, `import`, `preview`, `approve`, `cancel`, `status` |
| `/kb` | Isolated private Obsidian notes | `status`, `sync`, `search` |
| `/steam` | Public game price lookup | `search`, `price`, or a direct query |
| `/bili` | Bilibili public text and account operations | `read`, `search`, `feed`, `discover`, `subscribe`, `status`; see `/bili help` |
| `/reset` | Clear the current conversation | Owner may target `group:<id>` or `qq:<id>` |

Examples:

```text
/memory search apple pie
/memory add Keep this preference
/lore query What organization does Exusiai belong to?
/style status
/offline status
/cost
/life diary
/video create A lunch break at Penguin Logistics
/kb search project notes
/steam price Portal 2
/bili read <BV-id>
/bili subscribe keyword Arknights
```

`/video create` prepares a brief; it does not generate or publish a video. Import a real Updream export, review that exact version, then approve it. `/life preview` never publishes. Account, private-note and write actions keep their existing owner/private-chat permissions.
