# Возможности Paseo 0.8.0, которые касаются переноса orch

Сверено 2026-09-15 с установленным `@getpaseo/cli 0.8.0`
(`/usr/lib/node_modules/@getpaseo/cli`, типы в `node_modules/@getpaseo/{plugin,client,protocol}/dist`)
и исходниками `github.com/getpaseo/paseo` на теге `v0.8.0` (клон `/tmp/paseo-src`,
коммит `b8e24677 chore(release): cut 0.8.0`). Живой демон: `paseo daemon status --json`,
`paseo provider ls`, `~/.paseo/config.json` (только чтение).

Сокращения путей:
- `SRV` = `/tmp/paseo-src/packages/server/src/server`
- `PLG` = `/usr/lib/node_modules/@getpaseo/cli/node_modules/@getpaseo/plugin/dist`
- `CLI` = `/usr/lib/node_modules/@getpaseo/cli/node_modules/@getpaseo/client/dist`
- `PROTO` = `/usr/lib/node_modules/@getpaseo/cli/node_modules/@getpaseo/protocol/dist`
- `REF` = `/tmp/paseo-src/public-docs/plugins/v0.8/reference.md`

Метки: **есть** — прочитано в коде/типах; **есть (док)** — только в документации;
**нет** — не найдено ни в коде, ни в доках; **расхождение** — доки и код говорят разное.
Руками (создание агентов, плагины) ничего не гонялось: задача была только читать.

## 0. Состояние этой машины

- Демон 0.8.0, standalone (не desktop), `home=/home/dev/.paseo`. `status` сообщает
  `listen: 127.0.0.1:8075`, а в `config.json` `daemon.listen = 127.0.0.1:6767` —
  значит, адрес переопределён окружением/флагом запуска. Проверить перед интеграцией.
- `daemon.mcp.injectIntoAgents: true` (по умолчанию false, `public-docs/mcp.md`).
- `pluginsEnabled` в `config.json` **отсутствует** = false. `paseo plugin ls` пуст.
  Включение плагинов требует явного согласия владельца (правило из скилла paseo-plugin).
- `daemon.auth.password` не задан → любой локальный процесс имеет полный доступ к WS и может
  звать `/mcp/agents?callerAgentId=<любой id>`, выдавая себя за агента (`SRV/auth.ts:136-160`,
  `SRV/websocket-server.ts:502-505`).
- `~/.claude/skills` и `~/.agents/skills` — симлинки на `/home/dev/projects/vps-dev/session/skills`.
  Синхронизация скиллов Paseo (`SRV/orchestration-skills/internal/paths.ts:17-24`) пишет сквозь них,
  поэтому в репо vps-dev появились неотслеживаемые `session/skills/paseo*`. `~/.codex/skills` — копии.
- Провайдеры: `claude` (available, режимы Plan/Always Ask/Accept Edits/Auto/Bypass),
  `codex` (available, Default/Auto-review/Full Access), `opencode` (available, Build/Plan),
  `copilot`, `pi` — unavailable, `omp` — disabled.

## 1. Агенты

### Модель и статусы
- **есть** Статусы агента: `initializing | idle | running | error | closed`
  (`REF:1190`, `docs/agent-lifecycle.md`). `closed` = запись на диске без живого
  процесса провайдера, возобновляемая. Отдельного статуса «ждёт человека» нет:
  это `requiresAttention: boolean` + `attentionReason: "finished" | "error" | "permission" | null`
  + `pendingPermissions[]` в снимке агента (`REF:1199-1200`, `CLI/index.d.ts:250`).
- **есть** Статус воркспейса агрегированный: `needs_input | failed | running | attention | done`
  (`REF:1178`), считается по `workspaceId`.
- **есть** Хранение: `$PASEO_HOME/agents/{cwd-с-дефисами}/{agent-id}.json`
  (`docs/agent-lifecycle.md`, «Storage»). Таймлайн в памяти демона
  (`SRV/agent/agent-timeline-store.ts:138 InMemoryAgentTimelineStore`); после перезапуска
  история поднимается из нативной сессии провайдера.

### Создание
Три входа, у всех общий путь `AgentManager.createAgentInternal` (`SRV/agent/agent-manager.ts:1208`):

1. **SDK / плагин** — `paseo.agents.create(opts)` или `paseo.workspaces.ref(id).agents.create(opts)`
   (`CLI/index.d.ts:152-169`):
   ```ts
   interface PaseoAgentCreateOptions {
     config: {
       provider: string;            // "provider/model", напр. "claude/opus", "codex/gpt-5.5"
       modeId?: string; thinkingOptionId?: string; featureValues?: Record<string, unknown>;
       options?: ProviderOptions;   // provider-native, валидирует провайдер
       systemPrompt?: string;       // см. ниже
       toolPolicy?: { preapproved: { kind: "mcp"; server: string; tool: string }[] };
       mcpServers?: Record<string, McpStdioServerConfig | McpHttpServerConfig | McpSseServerConfig>;
     };
     cwd: string; parent?: string | PaseoAgentHandle; title?: string | null;
     env?: Record<string, string>; prompt?: string; clientMessageId?: string;
     outputSchema?: Record<string, unknown>; images?; attachments?; git?; worktree?;
     autoArchive?: boolean; labels?: Record<string, string>;
   }
   ```
2. **MCP `create_agent`** (`SRV/agent/tools/paseo-tools.ts:1406`): `title`, `provider`,
   `initialPrompt`, опц. `workspaceId`, `notifyOnFinish`, `settings{modeId,thinkingOptionId,features}`,
   `labels`, `background`. **Нет** `systemPrompt`, `env`, `mcpServers`, `outputSchema`.
3. **CLI `paseo run`**: `--provider --model --thinking --mode --workspace --new-workspace
   --worktree-mode --new-branch --base --env k=v --label k=v --output-schema --title -d`.
   **Нет** `--system-prompt`.

- **есть** `systemPrompt` на агента, сохраняется в записи (`SRV/agent/agent-storage.ts:29`).
  Маппинг: Claude — `systemPrompt: { type:"preset", preset:"claude_code", append }`, т.е.
  **дописывается** к пресету Claude Code, CLAUDE.md грузятся (`SRV/agent/providers/claude/agent.ts:3235,3291`);
  Codex — `developer_instructions` (`SRV/agent/providers/codex-app-server-agent.ts:3677,3873`);
  OpenCode — склейка (`SRV/agent/providers/opencode-agent.ts:3506`). К нему всегда
  доклеивается глобальный `daemon.appendSystemPrompt` из config (`SRV/config.ts:503`).
- **есть** `outputSchema`: нативно только Codex (`codex-app-server-agent.ts:4036`) и OpenCode
  (`opencode-agent.ts:3859`). В Claude-провайдере не используется (grep пуст).
  CLI `--output-schema` сделан поверх промпта: просит JSON, валидирует, до 2 повторов
  (`packages/cli/src/commands/agent/run.ts:228`), только в foreground.
- **есть** `env` на создание и на каждое открытие сессии (хук `agent.session_open`);
  env-оверрайды **не сохраняются** в записи агента (`REF:536-537`). Демон сам ставит
  `PASEO_AGENT_ID`, `PASEO_AGENT_CWD` (`REF:525`).
- **есть** `labels` (произвольные строки) — годятся для привязки агента к задаче orch.

### Промпт, ожидание, результат
- **есть** `handle.send(text, {messageId?, images?, attachments?})` — отправка без ожидания;
  `handle.run(text, {timeoutMs})` — отправка + ожидание; `handle.waitForFinish(timeoutMs?)`
  (`CLI/index.d.ts:260-265`). Результат:
  `{ status: "idle" | "error" | "permission" | "timeout"; final: AgentSnapshot | null; error: string | null; lastMessage: string | null }`
  (`CLI/daemon-client.d.ts:514-519`). `permission` = остановились на запросе к человеку.
  Таймаут агента не отменяет.
- **есть** На проводе `send_agent_message` имеет `activeTurnBehavior: "interrupt" | "steer"`
  (`PROTO/messages.d.ts:1082-1095`), но в `PaseoAgentSendOptions` SDK его **нет**.
  Идемпотентность: `messageId` (журналируется, повтор не дублирует — `docs/hub.md`),
  `create_agent_request.idempotencyKey` на создание.
- **есть** Таймлайн: `handle.timeline.refetch({direction,cursor,limit,projection})`,
  `handle.timeline.subscribe(handler)`; типы элементов `user_message | assistant_message |
  reasoning | tool_call | todo | error | notification | compaction | plugin`
  (`PROTO/agent-types.d.ts:303-325`). MCP: `get_agent_activity` (сводка), `get_agent_status`.
  CLI: `paseo logs <id> [--tail --filter tools|text|errors|permissions -f]`, `paseo inspect`, `paseo wait`.
- **есть** Отмена хода: MCP `cancel_agent`, CLI `paseo stop <id>`, `DaemonClient.cancelAgent`.
  **В `PaseoApi` (SDK плагина) метода отмены нет** (`CLI/index.d.ts:236-279`).
- **есть** Архив: `handle.archive()`, MCP `archive_agent`, CLI `paseo archive`; каскадно архивирует
  подагентов своего воркспейса (`docs/agent-lifecycle.md` «Archive»). Удаление: CLI `paseo delete`,
  MCP `kill_agent`. `autoArchive` — архив после первого терминального события хода.
- **есть** Смена модели/режима/thinking у живого агента: MCP `update_agent{settings:{model,modeId,thinkingOptionId,features}}`,
  `set_agent_mode`; `DaemonClient.setAgentModel/setAgentMode/setAgentThinkingOption/applyAgentConfig`
  (`CLI/daemon-client.d.ts:790-801`). Разговор тот же (Claude пересоздаёт query с `resume`,
  `claude/agent.ts:3270-3280`). **В `PaseoApi` нет**; CLI `paseo agent update` умеет только
  `--name --thinking --label`, модель — нет. Обход: `@getpaseo/client/internal/daemon-client`
  (internal, без гарантий) или MCP.
- **есть** Продолжение того же разговора: любой `send` в `idle`/`closed` агента — `ensureAgentLoaded()`
  поднимает нативную сессию под тем же ID. Импорт чужой сессии провайдера: `paseo import <session-id> --provider`.
  `rewindAgent(agentId, messageId, "conversation"|"files"|"both")`, форк (`buildAgentForkContext`).
  «Свежий» агент = просто новый `create`.

### Родители и видимость
- **есть** Агент, созданный через MCP `create_agent` агентом, получает label
  `paseo.parent-agent-id` и виден в UI в «Subagents track» родителя; из другого воркспейса —
  ещё и отдельной вкладкой там. Detach — только ручной жест пользователя (`docs/agent-lifecycle.md` «Relationships»).
  SDK: `create({parent})`. В хуках `PluginHookAgent.parentAgentId` (`PLG/server/lifecycle.d.ts:18`).
- **есть** `notifyOnFinish` (только MCP-путь, `SRV/agent/create-agent/create.ts:206`): родителю
  приходит обычный промпт в конверте `<paseo-system>…</paseo-system>`:
  `Agent <id> (<title>) finished|errored|needs permission|was closed.` + `<permission-request>{json}</permission-request>`
  + `<agent-response>` последнего сообщения, обрезка 4000 символов (`SRV/agent/agent-prompt.ts:380-420`).
- **есть** Внутренние агенты (`config.internal`) скрыты и не шлют уведомлений, хуки плагинов их не видят
  (`PROTO/agent-types.d.ts:461-465`, `agent-manager.ts:1215`). Через публичный API флаг не выставить.

### Провайдеры: паритет
Флаги (`claude/agent.ts:309`, `codex-app-server-agent.ts:213`, `opencode-agent.ts:129`):

| | claude | codex | opencode |
|---|---|---|---|
| session persistence / listing | да | да | да |
| dynamic modes | да | **нет** | да |
| mcpServers | да | да | да |
| rewind conversation / files | да / да | да / нет | нет / нет (both — да) |
| outputSchema нативно | **нет** | да | да |
| systemPrompt | append к пресету claude_code | developer_instructions | склейка |
| смерть процесса между ходами → error | да | нет (`agent-lifecycle.md`) | нет |

Claude работает через Claude Agent SDK (`canUseTool`, `settingSources`), не через TUI.
Ещё провайдеры: ACP (copilot, cursor, kimi, kiro, generic), pi, omp, кастомные через плагин
(`server.registerProvider`, `REF:192-221`).

## 2. Взаимодействие с человеком

- **есть** Вопросы и разрешения — один механизм `AgentPermissionRequest`
  (`PROTO/agent-types.d.ts:393-425`):
  ```ts
  type AgentPermissionRequestKind = "tool" | "plan" | "question" | "mode" | "other";
  interface AgentPermissionRequest { id; provider; name; kind; title?; description?;
    input?: AgentMetadata; detail?: ToolCallDetail; suggestions?; actions?: AgentPermissionAction[]; metadata? }
  type AgentPermissionResponse =
    | { behavior: "allow"; selectedActionId?; updatedInput?: AgentMetadata; updatedPermissions? }
    | { behavior: "deny"; selectedActionId?; message?: string; interrupt?: boolean };
  ```
  Claude: `ExitPlanMode` → `plan`, `AskUserQuestion` → `question` (`claude/agent.ts:1040-1047`).
  Ответ на вопрос: `allow` + `updatedInput: { answers: { "<header или текст вопроса>": "ответ" } }`;
  демон сам сводит ключи к полному тексту вопроса (`claude/agent.ts:198-230`). Codex: вопросы,
  заданные без остановки работы, получили формы ответа в 0.8.0 (CHANGELOG #4587).
- **есть** Запрос разрешения **не завершает ход** (`REF:423-424`): `agent.turn_ended` придёт только после ответа.
  Статус агента при этом обычно остаётся `running`; признак ожидания — `pendingPermissions.length > 0`
  или `attentionReason === "permission"` (`protocol/src/agent-state-bucket.ts:22-37` даёт `needs_input`).
- **есть** Детали по провайдерам (`/tmp/paseo-src/packages/server/src/server/agent/providers/`):
  Codex `request_user_input` → `kind:"question"`, ответы по `question.header`; **allow без валидных
  ответов молча выбирает первый вариант** (`codex-app-server-agent.ts:4541-4551`); async-вопросы Codex
  с ключами `"Question 1"…` требуют ответа на все, иначе throw, ответ уходит новым промптом
  (`codex/async-questions.ts`). План Codex — синтетический запрос `CodexPlanApproval`, allow запускает
  новый ход. План Claude: actions `reject | implement | implement_resume` (`claude/agent.ts:1085-1115`),
  отвечать `selectedActionId`. OpenCode `question.asked` → `question`, ответы по header, мультивыбор через запятую.
  Демон не проверяет ответ на соответствие вариантам.
- **есть** CLI-подводные камни: `paseo permit allow <agent>` **без req_id одобряет все** ожидающие
  запросы; `--input <json>` для ответов; нет `--action`, так что план одобряется как `implement`
  (`packages/cli/src/commands/permit/allow.ts:128-133`). `paseo wait` выходит со статусом `permission`.
- **есть** Push только в нативном мобильном приложении (Expo, токены в `~/.paseo/push-tokens.json`,
  аренда 48 ч). Web/desktop — OS Notification API, только пока клиент подключён
  (`packages/app/src/utils/os-notifications.ts:166-195`); web-push нет.
- **есть** Как видит человек: карточка в таймлайне агента (web/desktop/mobile), статус воркспейса
  `needs_input`, in-app уведомление самому свежему активному клиенту, push через Expo
  (`SRV/push/push-service.ts:24`, мобильное приложение). Push только для `finished` и `permission`,
  **не** для `error` (`SRV/agent-attention-policy.ts:78`); подавляется, если клиент активен
  (порог 180 с) и смотрит на этого агента (`agent-attention-policy.ts:3`, `SRV/websocket-server.ts:2557`).
  «Mark as unread» для воркспейсов (0.8.0).
- **есть** Оркестратор может обнаружить ожидание: хук `agent.permission_requested`, снимок агента
  (`pendingPermissions`, `attentionReason:"permission"`), `waitForFinish → status:"permission"`,
  MCP `list_pending_permissions`, CLI `paseo permit ls`.
- **есть** Автоответ: `handle.respondToPermission({requestId, response})` (SDK/плагин),
  MCP `respond_to_permission`, CLI `paseo permit allow|deny <agent> [req]`. Что не ответили —
  остаётся человеку (`REF:416-421`). Уже закрытый запрос → ошибка.
- **нет** API, чтобы плагин сам поднял «attention»/push для агента или своей карточки.
  Добавленная плагином строка таймлайна уведомлений не шлёт. Есть только `clearAgentAttention`
  во внутреннем DaemonClient.

## 3. Воркспейсы

- **есть** Иерархия в сайдбаре: проект → воркспейсы → вкладки (агенты, терминалы, браузер, диффы)
  (`public-docs/workspaces.md`). Несколько агентов в одном воркспейсе — норма; несколько
  воркспейсов могут ссылаться на один worktree/каталог.
- **есть** Создание: `paseo.workspaces.create({title, source})`, `source.kind: "directory" | "worktree"`,
  для worktree `action: "branch-off" | "checkout"`, `branchName`, `baseBranch`,
  `checkoutSource:{kind:"change_request",forge,number}`; MCP `create_workspace{isolation,mode,branchName,baseBranch,branch,prNumber,worktreeSlug}`;
  CLI `paseo workspace create`. `setTitle`, `archive`, MCP `rename_workspace`. Worktree по умолчанию
  в `~/.paseo/worktrees/`, удаляется после архива последнего воркспейса.
- **есть** `paseo.json` в репо: `worktree.setup` (раз после создания), `teardown` (при архиве),
  `scripts` (`type:"service"` — супервизор, `$PASEO_PORT`, reverse proxy
  `http://<script>--<branch>--<project>.localhost:<daemon-port>`), `servicePorts.range|portScript`
  (`public-docs/worktrees.md:81-215`). Для воркспейсов из fork-PR — явное одобрение перед setup.
- **есть** `workspace.created` не является барьером готовности: агент может стартовать до конца setup (`REF:439-440`).

## 4. Расписания и heartbeat

- **есть** Schedule: cron (5 полей, `--every` компилируется в cron, TZ), каждый запуск — **новый агент**;
  list/inspect/update/pause/resume/run-once/logs/delete, `maxRuns`, `expiresIn` (`public-docs/schedules.md`,
  `paseo-tools.ts:2518-2862`). Хранится в `~/.paseo/schedules`.
- **есть** Heartbeat: cron-промпт в **существующего** агента (тот же разговор); только create/delete
  (MCP), CLI ещё `heartbeat update --cron`. Привязан к `PASEO_AGENT_ID` вызывающего.
- **нет** Триггеров по событиям (агент закончил, PR, файл). Для событий из внешнего мира доки
  отсылают к Hub (§8). Реакция на «агент закончил» внутри демона — только хуки плагина или notifyOnFinish.

## 5. Плагины (главное)

### Общее
- **есть** Язык: TypeScript/TSX, два входа: `index.server.ts` (Node-подпроцесс демона) и
  `index.client.tsx` (React Native внутри приложения: desktop, web через RN Web, iOS, Android).
  Код раскладывается по `client/`, `server/`, `shared/`; компилирует сам Paseo (`REF:80-116`).
  Серверу доступны `@getpaseo/plugin`, `/server`, `/server/provider`, `/server/acp`, `zod`
  **и любые зависимости, установленные в каталоге плагина** (`REF:184-190,1565`), любые Node API.
  Python-движок orch можно запускать дочерним процессом из серверной части — ограничений нет.
- **есть** Установка: `paseo plugin init|install <abs-path>|add owner/repo[:path] [--ref]|reload|enable|disable|remove|logs|ls|update`
  (`REF:1692-1722`); глобальный флаг `pluginsEnabled` + `paseo reload`, без рестарта демона.
- **есть** Песочницы нет: trusted, unsandboxed (`REF:27`).
- **есть** Серверная часть работает, даже когда ни одно приложение не подключено (`REF:262`).
- **есть** Падение подпроцесса: плагин снимается, pending RPC отклоняются, **автоперезапуска нет**
  (`SRV/plugins/runtime.ts:976-989`); нужен `paseo plugin reload`. Неудачный reload не
  возвращает старый бандл (`REF:1767`).
- **есть** Хранилище: `defineSettings({id, scope:"host", version, schema, migrate?})` +
  `server.registerSettings` + `useSettings` на клиенте (`REF:1031-1089`). Атомарная запись,
  переживает рестарт/reload/update, удаляется с плагином. Это JSON-документ под настройки,
  не база: для базы задач orch — свой SQLite в серверной части.

### Серверный контекст (`PLG/server/contracts.d.ts:10-14`, `PLG/server/lifecycle.d.ts`)
```ts
interface PluginServerContext extends PluginLifecycleRegistration {
  registerSettings(definition): void;
  handle(contract: PluginRpcContract<In, Out>, handler: (input, ctx: { paseo: PaseoApi }) => Out | Promise<Out>): void;
  registerProvider(provider: ProviderRegistration): void;
}
interface PluginLifecycleRegistration {
  on<N extends keyof PluginLifecycleEvents>(name: N,
     handler: (event: PluginLifecycleEvents[N], ctx: { paseo: PaseoApi; signal: AbortSignal }) => void | Promise<void>): () => void;
  before<N extends keyof PluginBeforeRequests>(name: N,
     handler: (input: { request: PluginBeforeRequests[N] }, ctx) => PluginBeforeRequests[N] | void | Promise<…>): () => void;
}
```

### Хуки: полный список (8 событий + 3 before, `SRV/plugins/lifecycle/index.ts:18-28`)

| Хук | Поля | Когда |
|---|---|---|
| `agent.created` | `agent` | обычное создание (не import/resume) |
| `agent.turn_started` | `agent, turnId` | начало живого хода |
| `agent.turn_ended` | `agent, turnId, outcome, timeline` | ход завершён / упал / отменён |
| `agent.permission_requested` | `agent, request` | появился запрос разрешения или вопрос |
| `agent.permission_resolved` | `agent, requestId, resolution` | ответ дан или запрос снят |
| `agent.archived` | `agent, archivedAt` | архив сохранён |
| `workspace.created` | `workspace` | запись создана, каталог есть |
| `workspace.archived` | `workspace` | архив сохранён |
| before `agent.create` | `config: AgentSessionConfig, env?` | можно менять всё, кроме `cwd`/`internal` |
| before `agent.session_open` | `agentId, workspaceId, provider, cwd, reason: create\|resume\|refresh\|import, purpose: interactive\|history, env` | меняется только `env` |
| before `workspace.create` | `source, title?, firstAgentContext` | весь запрос |

```ts
interface PluginHookAgent { id; workspaceId: string | null; parentAgentId: string | null; provider; cwd; title: string | null }
type PluginTurnOutcome = { kind: "completed" } | { kind: "failed"; error: { message; code? } } | { kind: "canceled"; reason };
"agent.turn_ended": { agent: PluginHookAgent; turnId: string | null; outcome: PluginTurnOutcome; timeline: readonly AgentTimelineItem[] };
```
- `timeline` — полный снимок, включая прошлые ходы; финальный текст = склейка `assistant_message`
  после последнего `user_message` (пример `plugin-examples/lifecycle-actions/server/inspect.ts`).
  Вызовы инструментов — элементы `tool_call` там же.
- Нет событий: `agent.status_changed`, `agent.idle`, `agent.error` отдельно (есть только outcome хода),
  `agent.updated`, `workspace.setup_finished`, событий терминалов/скриптов/расписаний.
- Семантика: live, best effort, **без replay, персистентности и ретраев**; события могут
  перекрываться; таймаут хука 30 с (before-хук при таймауте валит операцию); ошибка
  обработчика события только логируется (`REF:539-552`). Пока плагин лежит или демон
  перезапускается, события теряются → orch всё равно нужна реконсиляция по снимкам.
- before `agent.create` срабатывает для **всех** путей создания (UI, MCP, CLI, schedule, SDK),
  потому что вызывается в `AgentManager.createAgentInternal` (`SRV/agent/agent-manager.ts:1215`),
  кроме internal-агентов. Порядок: по ID плагина, внутри — по порядку регистрации; без deep merge.

### PaseoApi внутри плагина (`CLI/index.d.ts:236-369`)
- `agents`: `list, ref, create, subscribe`; handle: `send, run, waitForFinish, respondToPermission,
  commands, archive, detach, refresh, current, subscribe, timeline.{append,refetch,subscribe}`.
- `workspaces`: `list, ref, open, create, archive, subscribe`; handle: `agents.create, terminals, setTitle, archive`.
- `terminals`, `projects.{list,subscribe}`, `providers.{listModels,listModes,listFeatures,listAvailable,snapshot,refresh,diagnostic,listUsage}`,
  `config.{get,patch}`.
- **Нет** в PaseoApi: cancel/interrupt, delete, set model/mode/thinking, clear attention,
  schedules/heartbeats, pending permissions list (есть только в снимке агента).

### Типовые рецепты (сигнатуры)
Реакция на конец хода и следующий шаг:
```ts
server.on("agent.turn_ended", async ({ agent, outcome, timeline }, { paseo, signal }) => {
  if (outcome.kind !== "completed") return;
  const text = latestOutputText(timeline);
  await paseo.agents.ref(agent.id).send("следующий промпт");               // тот же разговор
  // или новый агент следующей роли:
  await paseo.workspaces.ref(agent.workspaceId!).agents.create({
    config: { provider: "codex/gpt-5.5", systemPrompt: "...", mcpServers: {...} },
    prompt: "...", labels: { "orch.task": "T1", "orch.step": "review" },
  });
});
```
Кнопки решения человека прямо в таймлайне агента:
```ts
// сервер: карточка (перезапись по тому же id = обновление)
await paseo.agents.ref(agentId).timeline.append({ type: "plugin", id: "gate-T1", kind: "orch-gate", version: 1, data: {...} });
server.handle(decide, async ({ taskId, choice }, { paseo }) => { /* движение задачи */ return { ok: true }; });
// клиент
client.addTimelineRenderer({ kind: "orch-gate", version: 1, schema, Component: GateCard });
function GateCard({ item, theme }: PluginTimelineItemProps<Data>) {
  const decideRpc = useRpc(decide);   // работает: рендерер обёрнут в PluginRuntimeBoundary
  return <Pressable onPress={() => decideRpc({ taskId: item.data.taskId, choice: "approve" })}>…</Pressable>;
}
```
`PluginRuntimeBoundary` вокруг рендерера — `packages/app/src/plugins/timeline/view.tsx:92-99`.
Ограничения карточек: `data` ≤ 64 KiB; строки живут в памяти демона и **не переживают
рестарт демона** (`docs/plugins.md:390-393`); уведомлений не порождают.

### UI-поверхности (всё — React Native компоненты, не HTML)
- `addSurface` + `addSidebarItem({id,title,icon,surface})` — полноэкранная страница из сайдбара.
- `addWorkspacePanel({id,title,icon,context:"workspace"|"agent",locations?:["workspace","explorer"],Component})` — вкладка рядом с агентами.
- `addCommandCenterItem({id,title,icon,keywords?,context:"global"|"workspace"|"agent",onSelect})` — ⌘K.
- `addSlashCommand({name,description,argumentHint,context:"workspace"|"agent",onSubmit})` — `/cmd args` в композере, агенту не уходит; не ждёт промис, не работает при вложениях.
- `addHeaderButton({id,workspaceId,button})`, `addComposerPill({id,workspaceId,agentId,button})` →
  `{update, remove}`; `behavior: {kind:"action",onPress} | {kind:"menu",items} | {kind:"popover",Content}` (`REF:1298-1456`).
- `addTimelineTransformer({id,query:{itemType},transform})` (синхронный, детерминированный) + `addTimelineRenderer`.
- `addAttachmentSource`, `addTheme`, `addSettingsScreen`; host UI: `Modal`, `useToast`, `Icon`, `FlatList`, `TextInput`, `copyText`
  (`@getpaseo/plugin/client/react-native`); `@tanstack/react-query`.
- Хуки данных: `useAgent(id, selector)`, `useWorkspace(id, selector)`, `usePaseo()`, `useRpc(contract)`, `useSettings(def)`.
- Callback'и клиента получают `paseo`, `rpc`, `openSurface`, `openPanel`, `openSettings`.
- **нет** HTML/WebView-панелей, DOM (кроме `client/web.ts` под `Platform.OS==="web"`).
- **нет** серверных slash-команд (`REF:463` в скилле).

### RPC плагина
`defineRpc({name, input: zod, output: zod})` в `shared/`, `server.handle(contract, handler)`,
на клиенте `useRpc(contract)` или `rpc(contract, input)` из callback'а. Валидация с обеих сторон.
Сессия подпроцесса `plugin:<id>` живёт, пока жив процесс.

## 6. MCP, который получают агенты

- **есть** Механика: к агенту добавляется HTTP MCP-сервер `paseo` с
  `url: http://<host>:<port>/mcp/agents?callerAgentId=<agentId>` и `Authorization: Bearer <per-run token>`
  (`SRV/agent/runtime-mcp-config.ts:3-58`, маршрут `SRV/bootstrap.ts:1439-1560`). Работает только при
  TCP-listen. Пользовательский `mcpServers.paseo` перекрывает его. OpenCode (с bridge) и OMP получают
  каталог нативно, без MCP (`agent-manager.ts:5107-5123`).
- **расхождение** Default `injectIntoAgents`: `config.ts:529-530` и доки — false, `bootstrap.ts:534,652` — true
  при сборке конфига напрямую. Здесь явно true, так что неважно.
- **нет** Глобального `mcpServers` в `config.json` (схема `.strict()`, `SRV/persisted-config.ts:230-336`),
  в профилях и provider overrides тоже нет. Pi и OMP внешние MCP не поддерживают — создание падает
  (`agent-manager.ts:3468-3480`).
- **есть** Разные наборы Paseo-инструментов по ролям — только через кастомные provider ID
  (`agents.providers.<id>{extends, label, paseoTools, env, …}`, `protocol/src/provider-config.ts:52-66`),
  на которые ссылаются профили.
- **есть** `daemon.mcp.enabled` (default true), `daemon.mcp.injectIntoAgents` (default false; здесь true).
  Для Claude/Codex инструменты могут идти нативно, а не через MCP (`supportsNativePaseoTools`).
  Каталог фиксируется при запуске сессии: после смены — новый агент или reload (`public-docs/mcp.md`).
- **есть** Каталог (`SRV/agent/tools/paseo-tools.ts`, строки регистрации):
  `create_workspace` 1217, `list_workspaces` 1341, `archive_workspace` 1363, `create_agent` 1406,
  `send_agent_prompt` 1868, `get_agent_status` 1958, `list_agents` 2008, `cancel_agent` 2067,
  `archive_agent` 2091, `kill_agent` 2120, `update_agent` 2141, `rename_workspace` 2183,
  `list_workspace_scripts` 2243, `start_workspace_script` 2267, `stop_workspace_script` 2294,
  `list_terminals` 2320, `create_terminal` 2368, `kill_terminal` 2407, `capture_terminal` 2438,
  `send_terminal_keys` 2482, `create_schedule` 2518, `create_heartbeat` 2568, `delete_heartbeat` 2617,
  `list_schedules` 2638, `inspect_schedule` 2663, `pause_schedule` 2686, `resume_schedule` 2712,
  `delete_schedule` 2738, `update_schedule` 2764, `schedule_logs` 2836, `run_schedule_once` 2862,
  `list_providers` 2883, `list_models` 2904, `list_profiles` 2932, `inspect_provider` 2956,
  `get_agent_activity` 3018, `set_agent_mode` 3074, `list_pending_permissions` 3098,
  `respond_to_permission` 3132, `speak` 1166 (голос), плюс `browser_*` при включённых browser tools.
  Схемы входа различаются для agent-scoped и top-level вызова (`paseo-tools.ts:1098,1145`).
- **есть** Урезание по провайдеру: `agents.providers.<id>.paseoTools = { enabled: false }` или
  `{ disabledTools: [...] }`, профили через `extends` политику не наследуют (`public-docs/mcp.md`).
  Это не граница безопасности.
- **нет** Способа добавить свои инструменты **в каталог Paseo** (конфиг или плагин).
- **есть** Способ дать каждому агенту свой MCP-сервер (например, с `orch_done(outcome)`):
  плагин в `before("agent.create")` дописывает `config.mcpServers.orch = {type:"http", url}` или stdio
  (`REF:264-303`, `plugin-examples/agent-configuration`). Конфиг сохраняется с агентом, значит,
  действует и на resume. HTTP-сервер может поднять сама серверная часть плагина. Провайдер должен
  поддерживать внешние MCP (`requireExternalMcpSupport`, `agent-manager.ts:1240`); у claude/codex/opencode флаг true.
  `toolPolicy.preapproved` даёт предодобрение конкретных MCP-инструментов (не спрашивать разрешение).
  Идентификацию вызывающего агента даёт `PASEO_AGENT_ID` в env (для stdio-сервера) или токен в URL/заголовке.
- Альтернатива без плагина: агент зовёт CLI (`paseo …`) или свою команду `orch done` из shell — как сейчас.

## 7. Скиллы и системные инструкции

- **есть (док)** Paseo не протаскивает скиллы через API провайдера. Свои 4 скилла ставит в
  окружение хоста: Settings → host → Agents → Orchestration skills или `npx skills add getpaseo/paseo`,
  обновляет выбранные при старте (`public-docs/skills.md`). Дальше провайдер читает их сам
  (Claude — `settingSources`, т.е. `~/.claude`, CLAUDE.md проекта).
- **есть** `handle.commands()` — список slash-команд и скиллов, реально загруженных живой сессией.
- **есть** Per-agent `systemPrompt` (append) — только через SDK/плагин/before-хук, не через MCP/CLI.
  Глобальный `daemon.appendSystemPrompt` в config.
- **есть** Agent profiles: provider, model, modeId, thinkingOptionId, featureValues, notes
  («When to use») — только настройки запуска, без промпта и MCP (`public-docs/agent-profiles.md`).
  В `create_agent` параметра profile нет, агент материализует профиль сам.

## 8. Встроенные «конвейеры»

- **есть** `paseo-handoff`, `paseo-committee`, `paseo-advisor` — чистые промпт-скиллы поверх
  `list_profiles` + `create_workspace` + `create_agent` (+ notifyOnFinish). Никакой серверной логики.
- **нет** `paseo chat` и `paseo loop` удалены в 0.4.0 (CHANGELOG #3053). Схемы `PROTO/loop/*`
  (worker/verifier/итерации) и `PROTO/chat/*` остались в протоколе, CLI-команд нет; обработчики
  в сервере не проверялись — считать мёртвым кодом.
- **есть (док)** Paseo Hub — отдельный сервис (`npx @getpaseo/hub` self-host или hub.paseo.sh):
  триггеры GitHub/Slack/Discord/manual → workflow `.paseo/workflows/*.yml` из упорядоченных шагов
  с `if`, структурным `output.schema`, `max_runtime`/`idle_timeout`, инструментами агента
  `hub.reply`/`hub.finish_execution`; маршрутизация по enum-выходам предыдущего шага
  (`public-docs/hub/workflows.md`, `concepts.md`). Нет циклов/возвратов на шаг назад и нет
  человеческих ворот в описании; при оффлайн-демоне событие не ставится в очередь (`hub/faq.md`).
  Демон с Hub связывается через `paseo hub connect` и право `hub.execute`.
- **нет** Досок задач. «Tasks» в композере — это `todo`-список провайдера (TodoWrite), не задачи.
  `packages/server/src/tasks/` (TaskStore с зависимостями и `getReady`) нигде не импортируется — мёртвый код.
  Схемы chat/loop помечены `COMPAT(chatRooms)`/`COMPAT(agentLoops)` — оставлены после удаления фич.

## 9. Ограничения и подводные камни

- **расхождение** Перезапуск демона. `public-docs/troubleshooting.md:95`: «Running agents keep going».
  Код: при остановке `closeAllAgents()` закрывает рантайм каждого агента
  (`SRV/bootstrap.ts:1787,1831-1841`), `docs/agent-lifecycle.md`: закрытие при «daemon shutdown».
  Вывод по коду: идущий ход прерывается, агент остаётся `closed` и поднимается под тем же ID
  при следующем промпте/открытии. Фоновые Bash/Monitor внутри процесса Claude гибнут. Проверить руками.
- Таймлайн в памяти; плагинные строки таймлайна и хвост логов плагина теряются при рестарте.
- События хуков без replay: всё, что случилось при лежащем плагине/демоне, надо добирать сверкой
  (`agents.list`, `handle.refresh()`, `pendingPermissions`).
- Идущий ход прервётся и при смене модели у Claude? Не проверялось; смена модели пересоздаёт query.
- Плагин падает без автоперезапуска.
- API плагинов «For Paseo v0.8 beta» (`REF:11`), в 0.8.0 уже был ломающий переход (раздельные входы,
  новый API pills); `requirements.paseo` в манифесте, ставить верхнюю границу. Релизы примерно раз в
  неделю (0.4.0 13.08 → 0.8.0 10.09).
- `PaseoApi` урезан (нет cancel/model/delete); `@getpaseo/client/internal/daemon-client` — internal.
- Рендер ассистентского сообщения обрезается на 32 000 символов (0.7.2, #4166).
- Codex: `supportsDynamicModes:false`; вне хода смерть процесса не видна.
- Heartbeat нельзя изменить через MCP (только delete+create).
- Push для `error` не отправляется.
- Протокол WS: `/ws`, первое сообщение `hello{clientId, clientType, protocolVersion}`,
  `WS_PROTOCOL_VERSION = 1` строго (иначе close 4003). Контракт совместимости: только аддитивные
  изменения схем, новые фичи за `server_info.features` (`docs/protocol-compatibility.md`).
  Python-клиента нет; из Python — CLI `--json` или свой WS-клиент.
- Авторизация по умолчанию выключена (см. §0).
- Hub-сценарий `agent_request_outcome_unknown`: после рестарта недоставленный промпт не повторяется
  автоматически — проверить агента перед новым `messageId`.
