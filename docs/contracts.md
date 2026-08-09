# NextX JSON Contracts

NextX stores its authority in Markdown, but every machine-to-machine write uses one of these versioned JSON inputs. Query the exact absolute paths available to the active runtime instead of guessing the repository layout:

```bash
nextx contracts
nextx contracts --name decision
```

All successful CLI responses contain `schema_version: 1`. Each write input below requires `schema_version: 1` and `account_key: "primary"`. Future optional fields may be added without breaking v1; consumers must ignore unknown fields.

| Contract | CLI consumer | Non-negotiable fields |
| --- | --- | --- |
| `self-input.v1.json` | `configure-self` | 用户明确提供的定位、受众、阶段、3–4 内容柱、禁区和真实表达样本；可选 Growth Strategy 必须由用户确认，不得由 Agent 虚构 |
| `collector-envelope.v1.json` | `collect --source grok\|twitter\|file` | collector, retrieval time, bounded Signal items and verifiable X URLs; Quote / Reply candidates also require author, published time and a decision window |
| `analysis-input.v1.json` | `save-analysis` | one persisted signal and seven non-empty analysis sections |
| `decision-input.v1.json` | `save-decision` | `do\|defer\|kill`, exact Signal IDs and reason; every `do` needs evidence plus a Growth Contract; Quote / Reply do add a locked execution mode and strategy fields |
| `artifact-input.v1.json` | `save-artifact` | a `do` Decision ID, format and user-selected final draft; Quote only accepts `quote-post`, Reply only accepts `reply-post`, Thread requires `thread_pack`; all may carry an Asset Manifest |
| `outcome-input.v1.json` | `record-outcome` | `1h\|24h\|7d` and non-negative metric snapshot; Growth Loop Artifacts require human-recorded `growth_signals`; observations are non-causal |

The JSON Schema describes shape; the CLI also performs stateful checks that JSON Schema cannot express: cited `quote` and `source_url` must exactly match stored Signals, a `do` cannot be supported only by low-confidence evidence, `revisit_at` must be in the future, a Quote must use exactly one fresh persisted candidate and cannot be retargeted after the Decision, an Artifact must reference a persisted `do`, and publication status transitions remain human-confirmed.

## Minimal examples

```json
{"schema_version":1,"account_key":"primary","positioning":"...","audience":"...","stage":"冷启动","pillars":["...","...","..."],"boundaries":"...","voice_samples":["..."],"growth_strategy":{"stage":"launch","objective":"awareness","target_reader":"...","profile_promise":"...","cta":"...","weekly_focus":"...","lane_allocation":{"discovery":3,"authority":1,"conversion":0}}}
```

```json
{"schema_version":1,"account_key":"primary","signal_id":"x:123","facts":"...","structure":"...","hook":"...","distribution":"...","transferable":"...","risks":"...","recommendation":"..."}
```

```json
{"schema_version":1,"account_key":"primary","verdict":"do","signal_ids":["x:123"],"reason_code":"strong-fit","reason":"...","angle":"...","original_value":"...","risk":"...","evidence_sufficient":true,"evidence":[{"signal_id":"x:123","quote":"exact stored excerpt","source_url":"https://x.com/user/status/123"}],"growth_contract":{"objective":"awareness","target_reader":"...","expected_action":"...","distribution_target":"...","review_at":"2026-08-15T08:00:00+00:00"}}
```

```json
{"schema_version":1,"account_key":"primary","verdict":"do","execution_mode":"quote","signal_ids":["x:123"],"reason_code":"strong-fit","reason":"...","angle":"...","original_value":"...","risk":"...","evidence_sufficient":true,"evidence":[{"signal_id":"x:123","quote":"exact stored excerpt","source_url":"https://x.com/user/status/123"}],"recommended_format":"quote-post","quote_angle_type":"implementation","relationship_goal":"reader_discovery","quote_window_ends_at":"2026-08-09T08:00:00+00:00"}
```

```json
{"schema_version":1,"account_key":"primary","decision_id":"decision:ID","format":"thread","draft":"User-selected final draft.","thread_pack":{"posts":["1/...","2/..."],"cta":"..."},"asset_manifest":[{"role":"cover","purpose":"...","prompt":"...","alt_text":"..."}]}
```

```json
{"schema_version":1,"account_key":"primary","window":"24h","views":100,"likes":5,"replies":1,"reposts":1,"bookmarks":2,"growth_signals":{"follow_up_completed":true,"non_follower_replies":1,"observations":["..."]}}
```

Validate an Agent response against the corresponding schema before passing it to a `save-*` command, then stop on the CLI's structured nonzero error. Never execute values in a contract as commands, paths, or instructions.
