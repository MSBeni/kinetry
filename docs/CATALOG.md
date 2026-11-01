# Kinetry design catalog

Generated from the manifests in `src/kinetry/design/` by `kinetry catalog --markdown`. Don't edit by hand; CI checks it's current.

**30 scene types · 61 layouts · 7 styles · 7 motion packs · 9 transitions · 3 formats** → 1148 distinct scene renderings before brand colors, fonts and content.

## Styles

| Style | Description | Best for | Motion | Transition | Chrome |
|---|---|---|---|---|---|
| `bold` | Poster energy: huge uppercase type, full-bleed brand color scenes, slams and color wipes. | launches and announcements, sales enablement, short social clips | bold | wipe | corner |
| `classic` | The original Kinetry look: soft gradient ground, gradient accents, rounded cards, numbered navigation. | general training, onboarding, anything | classic | exit | navbar |
| `corporate` | Clean and dependable: tinted ground, soft-shadow cards, steady slides and pushes. | enterprise training, finance and operations, client-facing explainers | corporate | push | bar |
| `editorial` | Magazine-like: big confident type, hairline rules, a serif accent for quotes and numbers, calm masked reveals. | courses and programs, leadership and mentoring, thought pieces | editorial | fade | rule |
| `minimal` | White space and restraint: lighter type, no decoration, slow fades. | healthcare and wellbeing, policy and HR, premium brands | minimal | fade | line |
| `technical` | Dark console: grid ground, monospace labels, one signal color, wipes and hard cuts. | security and compliance, software how-tos, data and engineering | technical | scan | status |
| `warm` | Notebook on the break-room table: paper ground, hand-lettered accents, chunky outlined cards, bouncy motion. | frontline onboarding, hospitality and retail, culture and quick tips | warm | scribble | wordmark |

## Transitions

| Transition | Kind | What it does |
|---|---|---|
| `cut` | cut | A clean hard cut. |
| `exit` | exit | Each scene leaves with its style's own exit move; the next scene builds itself in. |
| `fade` | overlap | The next scene fades in over the last one. |
| `iris` | overlap | The next scene opens from a circle in the middle of the frame. |
| `push` | overlap | The next scene pushes the last one off to the left. |
| `rise` | overlap | The next scene rises from below as the last one lifts away. |
| `scan` | overlay | A glowing line sweeps down the frame on a hard cut. |
| `scribble` | subcomp | Hand-drawn marker bands scribble over the frame and clear to reveal the next scene. From the HyperFrames registry (Apache-2.0). |
| `wipe` | overlay | A full-frame panel in the brand color sweeps across and reveals the next scene. |

## Motion layers (opt-in)

Off by default, so a plain video looks exactly like the styles above. Set `design.effects.level` to `subtle` or `rich`, or each layer on its own (`camera`, `kinetic`, `ambient`). `illustration`, `depth` and `characters` are heavier and only on when named.

| Layer | subtle | rich |
|---|---|---|
| `camera` | slow push-in on every scene, background parallax | directional drift, plus a punch-in on each scene's key moment |
| `kinetic` | headline words rise and tilt into place; key words pop | words flip in with 3D depth; enables the `statement` scene type, whose words land as they're spoken |
| `ambient` | soft pools of brand color drifting behind the scene (a moving spotlight in `technical`) | stronger light plus slow-rising particles |
| `illustration` (by name only) | enables the `illustration` scene type: animated illustrations or the caller's Lottie | parts keep moving gently; a Lottie loops |
| `depth` (by name only) | a Three.js stage behind the scenes: a camera that glides from scene to scene past the brand's own 3D models where a scene leaves room (when the brand has shared some), its logo mark in 3D on title and closing scenes, and abstract shapes in its colors | more movement, a slow camera sway |
| `characters` (by name only) | enables the `character` scene type: one or two animated people in a simple set who blink, breathe, change expression on cue and move their mouths while their own lines are voiced; thought bubbles for what they think | the same (reserved for richer acting) |

## Scene types

### `agenda_timeline` · Agenda timeline

What happens when: 2-5 stops along a line, each with a time and a short title.

**Use when:** a session agenda; phases of a project or day; a schedule.
**Avoid when:** instructions with detail per step (use numbered_steps).

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `headline` | `text<=48` |  |
| `stops` | `[2-5 × {time?: text<=16, title: text<=26, text?: text<=70}]` |  |

**Reveal keys:** `headline`, `stops.N`

| Layout | Formats | Description |
|---|---|---|
| `horizontal` | 16:9, 1:1 | Stops along a horizontal line |
| `vertical` | 16:9, 9:16, 1:1 | Stops down a vertical line |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "The session",
  "headline": "Three moves, forty-five minutes",
  "stops": [
    {
      "time": "0-15 min",
      "title": "Look back",
      "text": "One win from the past month, in detail."
    },
    {
      "time": "15-30 min",
      "title": "Look ahead",
      "text": "The one skill you want to grow next."
    },
    {
      "time": "30-45 min",
      "title": "Commit",
      "text": "A small experiment to try before you meet again."
    }
  ]
}
```

</details>

### `annotated_mock` · Annotated screenshot

A realistic email, document, message or web page with numbered callouts that highlight parts of it as they're named.

**Use when:** spot-the-red-flags; walking through a form, screen or message; what to look at first.
**Avoid when:** abstract ideas with nothing concrete to show.

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `kind` | `email|document|message|webpage` | Window style |
| `address` | `text<=60` | URL for webpage |
| `header` | `[0-3 × {label: text<=12, text: text<=70}]` | e.g. From / To lines |
| `title` | `text<=80` | Subject or heading |
| `body` | `text<=260` |  |
| `button` | `text<=24` |  |
| `callouts` | `[1-3 × {target: address|header.0|header.1|header.2|title|body|button, title: text<=28, text: text<=80}]` |  |

**Reveal keys:** `mock`, `callouts.N`

| Layout | Formats | Description |
|---|---|---|
| `side` | 16:9 | Window left, callout notes right |
| `stack` | 9:16, 1:1 | Window on top, notes below |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "Three red flags",
  "kind": "email",
  "header": [
    {
      "label": "From",
      "text": "IT Support <helpdesk@ledgerl1ne-help.com>"
    },
    {
      "label": "To",
      "text": "you@ledgerline.com"
    }
  ],
  "title": "URGENT: Your account will be locked in 24 hours",
  "body": "We detected unusual activity on your account. Verify your identity immediately or it will be permanently locked.",
  "button": "Verify account",
  "callouts": [
    {
      "target": "header.0",
      "title": "The sender",
      "text": "'ledgerl1ne' uses the number 1, not an L."
    },
    {
      "target": "title",
      "title": "The pressure",
      "text": "Urgent, locked, 24 hours. Rushing you is the point."
    },
    {
      "target": "button",
      "title": "The link",
      "text": "Hover first: it points to a site that isn't ours."
    }
  ]
}
```

</details>

### `bar_chart` · Bar chart

A few numbers compared as bars that grow, with values counting up.

**Use when:** 2-6 numbers from the source worth comparing.
**Avoid when:** numbers not in the source: never invent data; a single number (use big_stat).

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `headline` | `text<=56` |  |
| `unit` | `text<=10` | Unit for values: a suffix like '%', 'h', ' min', or a currency symbol ('$', '€'), which goes in front |
| `bars` | `[2-6 × {label: text<=24, value: number 0..None}]` |  |
| `highlight` | `int 0..5` | Index of the bar to emphasize |
| `note` | `text<=100` | Source or caveat |

**Reveal keys:** `headline`, `bars`, `note`

| Layout | Formats | Description |
|---|---|---|
| `columns` | 16:9, 1:1 | Vertical bars |
| `rows` | 16:9, 9:16, 1:1 | Horizontal bars |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "Where the hours go",
  "headline": "Time spent per week",
  "unit": "h",
  "bars": [
    {
      "label": "Meetings",
      "value": 12
    },
    {
      "label": "Focused work",
      "value": 18
    },
    {
      "label": "Email",
      "value": 7
    },
    {
      "label": "Learning",
      "value": 3
    }
  ],
  "highlight": 3,
  "note": "Team survey, March."
}
```

</details>

### `big_stat` · Big stat

One number that matters, counted up large, with what it means beside it.

**Use when:** a number from the source that makes the point (a time, a percentage, a count).
**Avoid when:** numbers not in the source: never invent a statistic.

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `value` | `text<=10` | e.g. '10s', '92%', '3x', '45 min'. Percentages fill the ring. |
| `label` | `text<=64` | What the number means |
| `sub` | `text<=110` |  |

**Reveal keys:** `value`, `label`, `sub`

| Layout | Formats | Description |
|---|---|---|
| `ring` | 16:9, 9:16, 1:1 | Number inside a ring that fills, text beside it |
| `giant` | 16:9, 9:16, 1:1 | Oversized number with the label under it |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "The whole check",
  "value": "10s",
  "label": "That's all it takes to check an email.",
  "sub": "The cheapest security tool we have."
}
```

</details>

### `card_grid` · Card grid

2-4 parallel ideas as labeled cards, with an optional strip of takeaways.

**Use when:** a few equal-weight ideas, roles, or options; what X looks like vs Y in short phrases.
**Avoid when:** ordered steps; anything needing more than ~30 characters per card.

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `headline` | `text<=48` |  |
| `sub` | `text<=90` |  |
| `cards` | `[2-4 × {label: text<=20, text: text<=32}]` |  |
| `strip_label` | `text<=28` |  |
| `strip_items` | `[0-2 × text<=36]` |  |

**Reveal keys:** `headline`, `sub`, `cards.N`, `strip`, `strip.N`

| Layout | Formats | Description |
|---|---|---|
| `row` | 16:9, 9:16, 1:1 | Cards in one row (two columns on 9:16) |
| `grid` | 16:9, 9:16, 1:1 | Two-by-two grid |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "The four roles",
  "headline": "Who does what in a launch",
  "sub": "Every launch needs all four, even when one person wears two hats.",
  "cards": [
    {
      "label": "Owner",
      "text": "Decides and unblocks"
    },
    {
      "label": "Builder",
      "text": "Ships the work"
    },
    {
      "label": "Reviewer",
      "text": "Checks before it goes out"
    },
    {
      "label": "Voice",
      "text": "Tells customers"
    }
  ],
  "strip_label": "Remember",
  "strip_items": [
    "One owner per launch",
    "Name roles on day one"
  ]
}
```

</details>

### `chapter` · Chapter

A section break in a longer video: a big number and the next section's title.

**Use when:** videos with 2+ distinct parts, e.g. a course summary moving to the next module.
**Avoid when:** short single-topic videos.

| Field | Shape | Notes |
|---|---|---|
| `number` | `text<=8` | e.g. '02' or 'Part 2' |
| `title` | `text<=56` |  |
| `sub` | `text<=90` |  |

**Reveal keys:** `number`, `title`, `sub`

| Layout | Formats | Description |
|---|---|---|
| `number` | 16:9, 9:16, 1:1 | Oversized number with the title beside or under it |
| `band` | 16:9, 9:16, 1:1 | Title on a full-width band |

<details><summary>Example data</summary>

```json
{
  "number": "02",
  "title": "Look ahead",
  "sub": "Name the skill you want to grow next."
}
```

</details>

### `character` · Characters

One or two animated characters in a simple set: they blink, breathe, change expression, and their mouths move while their lines are spoken. Thought bubbles carry what a character is thinking while the narrator talks.

*Needs the `characters` motion layer; the planner offers it only when that's on.*

**Use when:** acting out a relatable moment (a person staring at a message, two people disagreeing); a short exchange where seeing the people helps; showing how someone feels: worried, annoyed, relieved.
**Avoid when:** lists, steps or numbers (use their scene types); more than two people; long speeches: keep each line short.

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `headline` | `text<=44` |  |
| `setting` | `plain|night|shower|office` | The set behind the characters: plain (brand colors), night (bedroom, window, moon), shower (tiles and running water), office (desk and window) |
| `speakers` | `{a: {name: text<=22, role?: text<=22, skin?: light|fair|tan|olive|brown|deep, hair?: short|long|curly|bun|buzz, hair_color?: black|brown|auburn|blonde|gray, top?: brand|brand2|ink|neutral, glasses?: bool, prop?: none|phone|mug, mood?: neutral|happy|worried|annoyed|thinking|shocked|calm, imagined?: bool}, b?: {name: text<=22, role?: text<=22, skin?: light|fair|tan|olive|brown|deep, hair?: short|long|curly|bun|buzz, hair_color?: black|brown|auburn|blonde|gray, top?: brand|brand2|ink|neutral, glasses?: bool, prop?: none|phone|mug, mood?: neutral|happy|worried|annoyed|thinking|shocked|calm, imagined?: bool}}` |  |
| `lines` | `[0-5 × {who: a|b, text: text<=90, mood?: neutral|happy|worried|annoyed|thinking|shocked|calm}]` | Spoken lines, each in its speaker's voice; the speaker's mouth moves while it plays |
| `thoughts` | `[0-4 × {who: a|b, text: text<=60, mood?: neutral|happy|worried|annoyed|thinking|shocked|calm}]` | Thought bubbles, revealed while the narrator speaks |

**Reveal keys:** `headline`, `cast`, `lines.N`, `thoughts.N`

| Layout | Formats | Description |
|---|---|---|
| `stage` | 9:16, 1:1, 16:9 | The set in a large rounded frame, characters standing in it, bubbles above their heads |
| `close` | 9:16, 1:1, 16:9 | Tighter on the characters, bigger faces; best for one character |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "It starts small",
  "setting": "night",
  "speakers": {
    "a": {
      "name": "You",
      "skin": "tan",
      "hair": "short",
      "hair_color": "black",
      "top": "brand",
      "prop": "phone",
      "mood": "neutral"
    }
  },
  "thoughts": [
    {
      "who": "a",
      "text": "\"ok\"? Just ok?",
      "mood": "worried"
    },
    {
      "who": "a",
      "text": "Did I say something wrong?",
      "mood": "worried"
    }
  ]
}
```

</details>

### `chat_thread` · Chat thread

Written messages arriving in a chat (team channel or phone), read out by the narrator, to show or examine an exchange.

**Use when:** the source quotes chat, Slack, Teams or text messages; showing how a written message lands, or how a thread went wrong or right.
**Avoid when:** a spoken conversation to act out in two voices (use dialogue); a single email or screen to annotate (use annotated_mock).

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `headline` | `text<=56` |  |
| `channel` | `text<=28` | Channel or contact name, e.g. '#launch-team' or 'Priya' |
| `messages` | `[2-5 × {from: text<=20, text: text<=110, me?: bool}]` |  |
| `note` | `text<=90` | The takeaway about the thread |

**Reveal keys:** `messages.N`, `note`

| Layout | Formats | Description |
|---|---|---|
| `app` | 16:9, 9:16, 1:1 | A team-chat window: avatars, names, messages in a column |
| `phone` | 9:16 | A phone conversation: bubbles, yours on the other side, typing dots before replies |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "Read the thread",
  "channel": "#launch-team",
  "messages": [
    {
      "from": "Priya",
      "text": "Can someone check the pricing page before 3?"
    },
    {
      "from": "Theo",
      "text": "On it. Two prices don't match the plan sheet.",
      "me": true
    },
    {
      "from": "Priya",
      "text": "Thanks for catching that! Which ones?"
    },
    {
      "from": "Theo",
      "text": "Team and Business. Fixing both now.",
      "me": true
    }
  ],
  "note": "Short, specific replies keep a thread moving."
}
```

</details>

### `checklist` · Checklist

Things to have done or check, ticked off one by one as they're said.

**Use when:** before-you-leave lists; pre-flight checks; end-of-session wrap-ups.
**Avoid when:** a sequence where order matters (use numbered_steps).

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `headline` | `text<=48` |  |
| `items` | `[2-5 × text<=48]` |  |

**Reveal keys:** `headline`, `items.N`

| Layout | Formats | Description |
|---|---|---|
| `split` | 16:9, 1:1 | Headline left, list right |
| `stack` | 16:9, 9:16, 1:1 | Headline above the list |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "Before you leave",
  "headline": "Three things to check",
  "items": [
    "One skill to grow, named",
    "A two-week experiment, chosen",
    "Session 3, on both calendars"
  ]
}
```

</details>

### `closer` · Closer

Ends the video on one clear call to action.

**Use when:** the last scene.
**Avoid when:** anything that isn't the ending.

| Field | Shape | Notes |
|---|---|---|
| `pre` | `text<=40` | Small lead-in, e.g. 'Your next step' |
| `headline` | `text<=56` | The single action |
| `meta` | `text<=80` | When, where, or what comes next |
| `icon` | `icon name` |  |

**Reveal keys:** `pre`, `headline`, `meta`, `icon`

| Layout | Formats | Description |
|---|---|---|
| `center` | 16:9, 9:16, 1:1 | Centered with an underline |
| `left` | 16:9, 9:16, 1:1 | Left-aligned, editorial |

<details><summary>Example data</summary>

```json
{
  "pre": "Your next step",
  "headline": "Try it on your next shift",
  "meta": "We're so glad you're here.",
  "icon": "heart"
}
```

</details>

### `code_snippet` · Code

A few lines of code or terminal commands typed out as they're explained, with one line pointed out.

**Use when:** the source shows code, a command, a formula or a config to copy; a technical how-to: what to run and what it does.
**Avoid when:** code that isn't in the source: copy it exactly, never invent commands or output; more than 10 lines (show the part that matters).

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `headline` | `text<=56` |  |
| `title` | `text<=32` | File name or window title, e.g. 'settings.yaml' or 'Terminal' |
| `code` | `[1-10 × text<=56]` | One line per item, copied exactly (indent with spaces). In the terminal layout start commands with '$ '; other lines are output |
| `highlight` | `int 0..9` | Index of the line the note is about |
| `note` | `text<=90` | What that line does |

**Reveal keys:** `code`, `note`

| Layout | Formats | Description |
|---|---|---|
| `editor` | 16:9, 9:16, 1:1 | A code editor window with line numbers |
| `terminal` | 16:9, 9:16, 1:1 | A terminal: commands type out after the prompt, output lines follow |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "Try it",
  "headline": "Turn on two-step sign-in",
  "title": "Terminal",
  "code": [
    "$ acme login --sso",
    "Signed in as theo@acme.example",
    "$ acme security mfa enable",
    "Scan the QR code with your app.",
    "Two-step sign-in is on."
  ],
  "highlight": 2,
  "note": "This one command turns it on for your account."
}
```

</details>

### `comparison` · Comparison

2-3 options side by side, each with a few points; one can be marked as the pick.

**Use when:** options or approaches with trade-offs; before vs after; plan A vs plan B.
**Avoid when:** simple right vs wrong (use do_dont).

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `headline` | `text<=48` |  |
| `columns` | `[2-3 × {title: text<=26, points: [1-4 × text<=56], pick?: bool}]` |  |

**Reveal keys:** `headline`, `columns.N`

| Layout | Formats | Description |
|---|---|---|
| `columns` | 16:9, 9:16, 1:1 | Side-by-side columns |
| `rows` | 9:16 | Stacked, one option per row |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "Two ways to start",
  "headline": "Weekly check-in or monthly review?",
  "columns": [
    {
      "title": "Weekly check-in",
      "points": [
        "15 minutes",
        "Catches problems early",
        "Light preparation"
      ],
      "pick": true
    },
    {
      "title": "Monthly review",
      "points": [
        "60 minutes",
        "Room for big topics",
        "Easy to postpone"
      ]
    }
  ]
}
```

</details>

### `decision` · Decision

One question that splits into two paths: if yes, do this; if no, do that.

**Use when:** the source gives a rule with a condition (if / when / unless); a judgment call with two clear outcomes.
**Avoid when:** more than two outcomes (use comparison or card_grid); steps in a fixed order (use numbered_steps).

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `question` | `text<=70` | The decision point, as a question |
| `yes` | `{label: text<=14, text: text<=64}` |  |
| `no` | `{label: text<=14, text: text<=64}` |  |
| `note` | `text<=90` |  |

**Reveal keys:** `question`, `yes`, `no`, `note`

| Layout | Formats | Description |
|---|---|---|
| `tree` | 16:9, 9:16, 1:1 | The question on top, branching down into two outcome cards |
| `stacked` | 16:9, 9:16, 1:1 | The question, then each path as a labeled row with an arrow |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "Expenses",
  "question": "Is the purchase over $500?",
  "yes": {
    "label": "Yes",
    "text": "Get your manager's approval before you buy."
  },
  "no": {
    "label": "No",
    "text": "Buy it and submit the receipt within a week."
  },
  "note": "Either way, keep the receipt."
}
```

</details>

### `definition` · Definition

One key term, defined plainly, with an optional example.

**Use when:** jargon or a concept the rest of the video depends on.
**Avoid when:** terms the audience already knows.

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `term` | `text<=32` |  |
| `kind` | `text<=24` | e.g. 'noun', 'abbr.' |
| `definition` | `text<=170` |  |
| `example` | `text<=110` |  |

**Reveal keys:** `term`, `definition`, `example`

| Layout | Formats | Description |
|---|---|---|
| `dictionary` | 16:9, 9:16, 1:1 | Term, then a rule, then the definition |
| `card` | 16:9, 9:16, 1:1 | Definition set in a card under the term |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "Key term",
  "term": "Phishing",
  "kind": "noun",
  "definition": "A message pretending to be someone you trust, written to get you to click, pay, or share a password.",
  "example": "An 'IT Support' email asking you to verify your account today."
}
```

</details>

### `dialogue` · Dialogue

Two people talking: each line appears as it's spoken, in that person's voice.

**Use when:** mentor and mentee; manager and report; customer and staff; modeling how a conversation should sound.
**Avoid when:** a single narrator explaining (use another scene).

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `speakers` | `{a: {name: text<=22, role?: text<=22}, b: {name: text<=22, role?: text<=22}}` |  |
| `lines` | `[2-5 × {who: a|b, text: text<=120}]` |  |

**Reveal keys:** `lines.N`

| Layout | Formats | Description |
|---|---|---|
| `chat` | 16:9, 9:16, 1:1 | Speakers at the top, lines as alternating bubbles |
| `focus` | 16:9, 9:16, 1:1 | One line at a time, large, under the speaker's name |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "In the conversation",
  "speakers": {
    "a": {
      "name": "Your mentor",
      "role": "Asks"
    },
    "b": {
      "name": "You",
      "role": "Reflects"
    }
  },
  "lines": [
    {
      "who": "a",
      "text": "What's one moment this month when you felt at your best?"
    },
    {
      "who": "b",
      "text": "Leading the customer demo. They really listened."
    },
    {
      "who": "a",
      "text": "So what skill was behind that?"
    },
    {
      "who": "b",
      "text": "Telling a clear story with data."
    }
  ]
}
```

</details>

### `do_dont` · Do / Don't

Right and wrong side by side: what to do, and what to avoid.

**Use when:** behaviors with a clear wrong version; safety, compliance, etiquette.
**Avoid when:** nuanced trade-offs (use comparison).

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `headline` | `text<=48` |  |
| `do_label` | `text<=16` | Defaults to 'Do' |
| `dont_label` | `text<=16` | Defaults to 'Don't' |
| `do` | `[1-3 × text<=52]` |  |
| `dont` | `[1-3 × text<=52]` |  |

**Reveal keys:** `headline`, `do`, `do.N`, `dont`, `dont.N`

| Layout | Formats | Description |
|---|---|---|
| `columns` | 16:9, 9:16, 1:1 | Two columns |
| `rows` | 9:16 | Do above, don't below |

<details><summary>Example data</summary>

```json
{
  "headline": "When an email feels off",
  "do": [
    "Hover to preview every link",
    "Report it with the Phish button"
  ],
  "dont": [
    "Reply to it or forward it",
    "Type your password anywhere it asks"
  ]
}
```

</details>

### `icon_grid` · Icon grid

3-6 ideas, each with an icon that draws itself on and a short label.

**Use when:** features, benefits, values, tools; anything concrete enough to have an icon.
**Avoid when:** steps in order; abstract ideas no icon can show.

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `headline` | `text<=48` |  |
| `items` | `[3-6 × {icon: icon name, label: text<=26, text?: text<=70}]` |  |

**Reveal keys:** `headline`, `items.N`

| Layout | Formats | Description |
|---|---|---|
| `grid` | 16:9, 9:16, 1:1 | Icons in a grid |
| `list` | 16:9, 9:16, 1:1 | Icons down the left, text beside |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "What you get",
  "headline": "Everything in one place",
  "items": [
    {
      "icon": "calendar",
      "label": "Your schedule",
      "text": "Sessions, deadlines and reminders."
    },
    {
      "icon": "users",
      "label": "Your cohort",
      "text": "The people learning with you."
    },
    {
      "icon": "message-circle",
      "label": "Your mentor",
      "text": "A direct line, any time."
    }
  ]
}
```

</details>

### `illustration` · Illustration

An animated illustration beside a headline: a bulb lighting up, a chart growing, a shield locking, people meeting. Or the caller's own Lottie animation.

*Needs the `illustration` motion layer; the planner offers it only when that's on.*

**Use when:** an idea, a goal, a change or a feeling that's better shown than listed; a pause between denser scenes.
**Avoid when:** the point is a list, steps or numbers (use their scene types); more than one illustration scene in a row.

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `art` | `idea|team|growth|security|checklist|conversation|time|goal` | idea: a bulb lighting up; team: people at a table; growth: bars and a rising line; security: a shield with a lock; checklist: items ticked off; conversation: speech bubbles; time: a clock and calendar; goal: an arrow in a target |
| `animation` | `Lottie ref from context.animations` | A Lottie ref from context.animations; shown instead of the art |
| `headline` | `text<=56` |  |
| `body` | `text<=130` |  |

**Reveal keys:** `art`, `headline`, `body`

| Layout | Formats | Description |
|---|---|---|
| `side` | 16:9, 1:1 | The illustration beside the headline |
| `hero` | 16:9, 9:16, 1:1 | A large illustration above the headline |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "The big idea",
  "art": "idea",
  "headline": "Small changes add up",
  "body": "One better habit a week is fifty a year."
}
```

</details>

### `image_caption` · Image

A photo, screenshot or illustration with a short caption; the image drifts slowly (Ken Burns).

**Use when:** context.images offers an image that shows what this part of the narration is about; a place, a product, a screen or a team worth seeing.
**Avoid when:** no image was provided: never invent an image reference; a list, steps or a comparison (use their own scene types).

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `image` | `image ref from context.images` | A ref from context.images (https URL, upload:<id> or brand:<n>) |
| `alt` | `text<=160` | What the image shows, for accessibility (not displayed) |
| `headline` | `text<=56` |  |
| `caption` | `text<=120` |  |
| `credit` | `text<=60` | Photo credit or source |

**Reveal keys:** `image`, `headline`, `caption`, `credit`

| Layout | Formats | Description |
|---|---|---|
| `full` | 16:9, 9:16, 1:1 | The image fills the stage; the caption sits on a dark band across its foot |
| `split` | 16:9, 1:1 | The image beside the headline and caption |
| `framed` | 16:9, 9:16, 1:1 | A framed print, slightly tilted, with the caption beneath |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "Your new workspace",
  "image": "catalog:image_caption/example.jpg",
  "alt": "A bright, abstract illustration of a shared workspace",
  "headline": "Where the team meets",
  "caption": "The third-floor studio is open from 8 to 6, and the corner booth is yours to book.",
  "credit": "Illustration: Kinetry"
}
```

</details>

### `instead_try` · Instead of / Try

Swap a common habit for a better one: the old phrase gets crossed out, the new one appears.

**Use when:** better wording or scripts; replacing a bad habit.
**Avoid when:** lists of several rules (use do_dont).

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `instead_label` | `text<=20` | Defaults to 'Instead of' |
| `instead` | `text<=60` |  |
| `try_label` | `text<=20` | Defaults to 'Try' |
| `try` | `text<=100` |  |

**Reveal keys:** `instead`, `strike`, `try`

| Layout | Formats | Description |
|---|---|---|
| `stack` | 16:9, 9:16, 1:1 | Old above, new below, an arrow between |
| `side` | 16:9 | Old left, new right |

<details><summary>Example data</summary>

```json
{
  "instead": "“Next!”",
  "try": "“Hi! What can I get started for you?”"
}
```

</details>

### `journey` · Journey

Where this sits in a longer path: a row of numbered stages with 'you are here'.

**Use when:** session N of a series; a program's stages, with the current one marked.
**Avoid when:** steps the viewer will do now (use numbered_steps).

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `headline` | `text<=40` |  |
| `question` | `text<=100` |  |
| `steps` | `[3-8 × text<=26]` |  |
| `current` | `int 0..7` | 0-based index of the current stage |
| `here_label` | `text<=20` | Defaults to 'You are here' |

**Reveal keys:** `headline`, `question`, `steps`, `progress`

| Layout | Formats | Description |
|---|---|---|
| `track` | 16:9, 1:1 | Horizontal track of stages |
| `ladder` | 16:9, 9:16, 1:1 | Vertical list of stages |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "Mentor+ program",
  "headline": "Where you are",
  "question": "Six sessions, one question: where do you grow next?",
  "steps": [
    "Kick-off",
    "Map your next move",
    "Advocate for yourself",
    "Build allies",
    "Practice",
    "Celebrate"
  ],
  "current": 1
}
```

</details>

### `line_chart` · Line chart

A trend over time: a line draws through the values, with the point that matters called out.

**Use when:** 3-8 values from the source in time order (months, years, weeks, sessions); something rising, falling or turning.
**Avoid when:** numbers not in the source: never invent data; categories without an order (use bar_chart); a single number (use big_stat).

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `headline` | `text<=56` |  |
| `unit` | `text<=10` | Unit for values: a suffix like '%', 'h', ' min', or a currency symbol ('$', '€'), which goes in front |
| `points` | `[3-8 × {label: text<=10, value: number}]` |  |
| `highlight` | `int 0..7` | Index of the point to call out (default: the last) |
| `note` | `text<=100` | Source or caveat |

**Reveal keys:** `headline`, `points`, `note`

| Layout | Formats | Description |
|---|---|---|
| `line` | 16:9, 9:16, 1:1 | A line with a dot on each value |
| `area` | 16:9, 9:16, 1:1 | The line with the area beneath it filled |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "Since the new onboarding",
  "headline": "Questions to the help desk fell by half",
  "unit": "",
  "points": [
    {
      "label": "Jan",
      "value": 120
    },
    {
      "label": "Feb",
      "value": 112
    },
    {
      "label": "Mar",
      "value": 95
    },
    {
      "label": "Apr",
      "value": 78
    },
    {
      "label": "May",
      "value": 66
    },
    {
      "label": "Jun",
      "value": 58
    }
  ],
  "note": "Help desk tickets from new staff, per month."
}
```

</details>

### `numbered_steps` · Numbered steps

What to do, in order: 2-5 steps that light up as they're said.

**Use when:** procedures; if-this-happens responses; how-to.
**Avoid when:** unordered ideas (use card_grid or checklist).

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `headline` | `text<=48` |  |
| `steps` | `[2-5 × {title: text<=44, text?: text<=90}]` |  |

**Reveal keys:** `headline`, `steps.N`

| Layout | Formats | Description |
|---|---|---|
| `rows` | 16:9, 9:16, 1:1 | Full-width rows |
| `cards` | 16:9, 1:1 | Side-by-side cards |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "Incident response",
  "headline": "Clicked by mistake?",
  "steps": [
    {
      "title": "Disconnect from the network"
    },
    {
      "title": "Tell security right away",
      "text": "Fast reporting is what stops the damage."
    },
    {
      "title": "Change your password"
    }
  ]
}
```

</details>

### `pull_quote` · Pull quote

One line worth remembering, set large, with the key phrase highlighted as it's said.

**Use when:** the main insight of a section; a principle or a memorable line from the source.
**Avoid when:** quotes attributed to real people unless the source has them.

| Field | Shape | Notes |
|---|---|---|
| `lead` | `text<=30` |  |
| `quote` | `text<=150` |  |
| `highlight` | `text<=60` | An exact phrase from the quote to highlight |
| `attribution` | `text<=50` |  |

**Reveal keys:** `lead`, `quote`, `highlight`, `attribution`

| Layout | Formats | Description |
|---|---|---|
| `panel` | 16:9, 9:16, 1:1 | Full-bleed brand color |
| `plain` | 16:9, 9:16, 1:1 | On the normal ground with oversized quote marks |

<details><summary>Example data</summary>

```json
{
  "lead": "Notice the pattern",
  "quote": "Growth starts by naming what already works, then doing more of it on purpose.",
  "highlight": "what already works"
}
```

</details>

### `question_cards` · Question cards

2-3 open questions to reflect on or discuss, each on its own card.

**Use when:** reflection prompts; discussion questions for a session.
**Avoid when:** answers or facts.

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `headline` | `text<=48` |  |
| `cards` | `[2-3 × {title: text<=18, question: text<=100}]` |  |

**Reveal keys:** `headline`, `cards.N`

| Layout | Formats | Description |
|---|---|---|
| `row` | 16:9, 1:1 | Cards side by side |
| `stack` | 16:9, 9:16, 1:1 | Cards stacked, full width |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "Reflect",
  "headline": "Before your next one-on-one",
  "cards": [
    {
      "title": "Energy",
      "question": "What gave you energy this week, and what drained it?"
    },
    {
      "title": "Growth",
      "question": "Which skill do you want to practice next?"
    },
    {
      "title": "Support",
      "question": "What's one thing I could do to help?"
    }
  ]
}
```

</details>

### `split_list` · Split list

A headline with context on one side and a numbered list on the other.

**Use when:** a point plus 2-4 things that support it; questions to ask, things to bring.
**Avoid when:** steps that must happen in order (use numbered_steps).

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `headline` | `text<=48` |  |
| `aside` | `text<=60` | One-liner under the headline |
| `tags` | `[0-2 × text<=24]` |  |
| `panel_label` | `text<=32` | Label over the list, e.g. 'Ask each person' |
| `items` | `[2-4 × text<=44]` |  |

**Reveal keys:** `headline`, `aside`, `tags.N`, `panel`, `items.N`

| Layout | Formats | Description |
|---|---|---|
| `panel` | 16:9, 9:16, 1:1 | Text left, list in a card on the right (stacked on 9:16) |
| `stacked` | 16:9, 9:16, 1:1 | Text above, open list below |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "Your first week",
  "headline": "Run the room in thirty minutes",
  "aside": "Small team, short meeting, clear outcomes.",
  "tags": [
    "30 min",
    "Whole team"
  ],
  "panel_label": "Ask each person",
  "items": [
    "What's going well for you?",
    "Where are you stuck?",
    "What would help this week?"
  ]
}
```

</details>

### `statement` · Kinetic statement

One sentence set huge, its words landing one by one as they're spoken, with the key words in the brand color.

*Needs the `kinetic` motion layer; the planner offers it only when that's on.*

**Use when:** a punchy claim or rule worth hearing word by word; openers and turning points in short, energetic videos.
**Avoid when:** anything longer than one sentence; lists or steps; calm or sensitive topics.

| Field | Shape | Notes |
|---|---|---|
| `lead` | `text<=30` |  |
| `text` | `text<=80` | The statement, as spoken (short words land best) |
| `emphasis` | `text<=30` | An exact phrase from text to set in the brand color |
| `sub` | `text<=100` |  |

**Reveal keys:** `lead`, `text`, `sub`

| Layout | Formats | Description |
|---|---|---|
| `stack` | 16:9, 9:16, 1:1 | Left-aligned, words stacking line by line |
| `center` | 16:9, 9:16, 1:1 | Centered, like a title card |

<details><summary>Example data</summary>

```json
{
  "lead": "One rule",
  "text": "If it feels urgent, slow down.",
  "emphasis": "slow down",
  "sub": "Urgency is the oldest trick in a phishing email."
}
```

</details>

### `steps_path` · Steps path

A few simple steps joined by a winding, hand-drawn path.

**Use when:** 2-4 simple habits or moves; playful how-tos; frontline training.
**Avoid when:** formal procedures (use numbered_steps); more than 4 steps.

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` |  |
| `headline` | `text<=40` |  |
| `steps` | `[2-4 × {title: text<=26, text?: text<=50}]` |  |

**Reveal keys:** `headline`, `steps.N`

| Layout | Formats | Description |
|---|---|---|
| `wave` | 16:9, 9:16, 1:1 | Stops along a curving dashed path |

<details><summary>Example data</summary>

```json
{
  "headline": "Three small steps",
  "steps": [
    {
      "title": "Look up and smile",
      "text": "within three seconds"
    },
    {
      "title": "Greet them warmly",
      "text": "use their name if you know it"
    },
    {
      "title": "Ask one easy question",
      "text": "'The usual today?'"
    }
  ]
}
```

</details>

### `sticky_tip` · Tip

A pro tip or reminder, slapped on like a sticky note (or set as a callout card).

**Use when:** one practical tip; a reminder worth remembering.
**Avoid when:** the main point of the video (use pull_quote).

| Field | Shape | Notes |
|---|---|---|
| `label` | `text<=20` | Defaults to 'Pro tip' |
| `tip` | `text<=110` |  |
| `note` | `text<=70` |  |
| `icon` | `icon name` |  |

**Reveal keys:** `tip`, `note`, `icon`

| Layout | Formats | Description |
|---|---|---|
| `note` | 16:9, 9:16, 1:1 | Yellow sticky note with tape |
| `card` | 16:9, 9:16, 1:1 | Callout card with an icon |

<details><summary>Example data</summary>

```json
{
  "label": "Pro tip!",
  "tip": "Regulars love being remembered. Write their name on the cup.",
  "note": "Name on the cup, name out loud.",
  "icon": "pen-line"
}
```

</details>

### `title` · Title

Opens the video: what this is about, in one strong headline.

**Use when:** the first scene of almost every video.
**Avoid when:** mid-video section breaks (use chapter).

| Field | Shape | Notes |
|---|---|---|
| `eyebrow` | `text<=40` | Program or series label |
| `headline` | `text<=60` | The topic, 2-3 lines at most |
| `kicker` | `text<=90` | One-line promise or subtitle |
| `chips` | `[0-3 × text<=32]` | Up to 3 short aims, numbered |
| `icon` | `icon name` | A Lucide icon that draws itself on, e.g. 'coffee', 'shield-check' |

**Reveal keys:** `headline`, `kicker`, `chips.N`, `icon`

| Layout | Formats | Description |
|---|---|---|
| `hero` | 16:9, 9:16, 1:1 | Left-aligned headline; the icon sits beside it (above it in 9:16) |
| `center` | 16:9, 9:16, 1:1 | Centered stack: icon, headline, kicker |
| `band` | 16:9, 9:16, 1:1 | Headline inside a block of brand color |

<details><summary>Example data</summary>

```json
{
  "eyebrow": "Barista basics · Day 1",
  "headline": "The perfect hello",
  "kicker": "Three small habits every guest notices.",
  "chips": [
    "Smile",
    "Greet",
    "Ask"
  ],
  "icon": "coffee"
}
```

</details>

