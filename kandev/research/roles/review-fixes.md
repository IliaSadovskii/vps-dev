# Review Fixes

## Наш замысел
Идёт после `Code Review` и `Security Review` во всех трёх маршрутах Kandev.
Работает в свежем контексте (`reset_agent_context`) — исполнитель правок не
видел, как писалась реализация, только диф и замечания предшественников.
Выполняется ровно один раз и может оказаться пустой (Discovery: `Review
Fixes, Final Verification | ревью что-то нашло` — колонка вообще не
запускает агента, если вход пуст). Дополнительный круг делается только
ручным возвратом карточки человеком: счётчика кругов в Kandev нет
(`/home/dev/projects/vps-dev/kandev/DEVELOPMENT-ROUTES.md:90-92, 226-227`).
Ревью-цикл официально не замкнут: после `Review Fixes` нет независимого
повторного ревью (`DEVELOPMENT-ROUTES.md:217-220`) — это осознанный gap, а
не решённый вопрос.

## Найденные аналоги

| Инструмент | Как называется роль | Где лежит |
|---|---|---|
| Kandev (свой же встроенный промпт) | `ci-auto-fix` / `mr-auto-fix` — «continuing work on a pull/merge request because Kandev detected new CI or review feedback» | `/tmp/kandev-v0.93.0/apps/backend/config/prompts/ci-auto-fix.md:1-28`, `mr-auto-fix.md:1-28` |
| claude-security (плагин) | связка `patch-generator` + `patch-verifier` — генератор фикса и независимый ревьюер патча | `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/claude-security/agents/patch-generator.md`, `patch-verifier.md` |
| Superpowers (obra) | skill `receiving-code-review` — приём и обработка ревью-фидбека (GitHub/human/subagent) | `github.com/obra/superpowers` → `skills/receiving-code-review/SKILL.md` (raw) |
| CodeRabbit | `Autofix` — авто-исправление review-комментариев со структурированными инструкциями | `docs.coderabbit.ai/finishing-touches/autofix` |
| kit-lite | явной отдельной роли нет; `build` продолжает сам себя после `review.md`, `pr` выносит нерешённые замечания человеку | `/home/dev/projects/kit-lite/roles/build.md:85-91`, `pr.md:57-58` |
| pr-review-toolkit (плагин) | явной роли-фиксера нет — только `code-reviewer`/`comment-analyzer` и т.д., которые «analyze and provide feedback only», правки делает человек/orchestrator вручную | `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/pr-review-toolkit/commands/review-pr.md:83-87`, `agents/comment-analyzer.md:79` |
| feature-dev (плагин) | явной роли нет; Phase 6 «Quality Review» — три `code-reviewer`, затем «Present findings to user and ask what they want to do» | `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/feature-dev/commands/feature-dev.md:101-109` |
| OpenHands | упоминается «resolver», но в актуальной документации по code review — только генерация ревью, отдельного шага классификации/резолва фидбека не описано | `docs.openhands.dev/openhands/usage/use-cases/code-review` (проверено WebFetch) |
| BMAD-METHOD | QA-агент делает adversarial review и «может зациклить назад на dev для фиксов» — общий multi-agent quality gate, без прямой цитаты про классификацию | вторично, из обзорных статей про `bmad-code-org/BMAD-METHOD` |

Прямого совпадения по названию роли нигде нет: почти везде это либо
встроенный CI/PR-бот (Kandev, CodeRabbit), либо часть более общего пайплайна
security-патчей (claude-security), либо skill приёма фидбека (Superpowers).
Отдельного «Review Fixes» как шага workflow с фиксированным местом между
двумя ревью и Final Verification — аналога с таким же контрактом не нашлось.

## Что кладут всегда

**Классификация «требует правки / не требует» перед любым действием** — 3 из
4 источников с выделенной ролью-фиксером:
- Kandev: «First classify the new PR feedback as actionable or
  non-actionable» (`ci-auto-fix.md:14`, дословно повторено в
  `mr-auto-fix.md:14`).
- CodeRabbit Autofix: действует только по «unresolved CodeRabbit review
  comments that include structured fix instructions» — комментарии без
  такого блока не считаются исполнимыми.
- Superpowers `receiving-code-review`: «External feedback — be skeptical, but
  check carefully» — фидбек проверяется на соответствие коду, обратную
  совместимость и архитектурный контекст, прежде чем что-то менять.

**Узкий охват правки, без побочных рефакторов** — во всех источниках,
которые вообще правят код:
- Kandev: «Preserve unrelated work and avoid broad refactors»
  (`ci-auto-fix.md:10`, `mr-auto-fix.md:10`).
- claude-security `patch-generator`: «keep the change **highly targeted**:
  touch only what closing this one finding requires. No drive-by refactors,
  no formatting sweeps, no dependency bumps, no "while I'm here" fixes to
  other bugs — even real ones» (`patch-generator.md:27`).
- claude-security `patch-verifier` проверяет это отдельным пунктом: «Scope.
  Changes unrelated to the finding — refactors, formatting, drive-by edits,
  fixes to other bugs — are objections» (`patch-verifier.md:27`).
- Superpowers: «implement in this order — blocking issues, simple fixes,
  complex fixes. Test each fix individually» — по одному пункту за раз,
  явный запрет батчить непрояснённый фидбек.
- `code-simplifier` (общий принцип охвата, не про ревью-фикс конкретно):
  «Focus Scope: Only refine code that has been recently modified or touched
  in the current session, unless explicitly instructed to review a broader
  scope» (`code-simplifier.md:41`).

**Никакого мержа/финализации в рамках самой роли** — Kandev прямо: «Do not
merge the pull request. Kandev handles auto-merge separately when the PR is
ready» (`ci-auto-fix.md:12`); claude-security идёт ещё дальше — патч вообще
не коммитится и не пушится, а выкладывается файлом, который применяет
человек («nothing is committed or pushed», `patch-generator.md:12`);
CodeRabbit Autofix тоже не мержит сам — коммитит в ветку или открывает
отдельный stacked PR, слияние — руками.

**Не делать действие только ради галочки/подтверждения** — Kandev: «Do not
push a commit merely to acknowledge feedback» (`ci-auto-fix.md:26`,
`mr-auto-fix.md:26`); Superpowers требует технических ответов в тред, а не
«Great point!»/«Thanks for catching that!» — то есть тоже против
действия/реплики без содержания.

## Что кладут иногда

- **Отдельный независимый верификатор после фикса.** claude-security строго
  разделяет `patch-generator` и `patch-verifier` — генератор не может сам
  себя одобрить («You never judge your own work», `patch-generator.md:12`;
  «you are the ONLY automated check», `patch-verifier.md:12`). У Kandev в
  самом шаге такого разделения нет: `ci-auto-fix`/`mr-auto-fix` сами и чинят,
  и сами отчитываются, а независимая перепроверка (`Final Verification`)
  делает другую работу — полный прогон, а не ревью корректности фикса.
- **Явная ветка «CI ещё не готово».** Только у Kandev: «Pending-only PR
  snapshots are also non-actionable... do not poll indefinitely»
  (`ci-auto-fix.md:20-23`). У CodeRabbit есть близкий, но более узкий случай:
  «If no valid unresolved instructions are found, Autofix skips execution and
  reports that no fixes were applied» — это про отсутствие инструкций, не
  про ожидание CI.
- **Ответ и резолв треда как обязанность именно фикс-роли.** Kandev: «reply
  to that thread with the fix summary and resolve the addressed PR review
  threads so they do not keep the PR blocked» (`ci-auto-fix.md:9`);
  Superpowers требует «reply in the comment thread, not as a top-level PR
  comment». У claude-security и code-simplifier этого нет вовсе — это либо
  не их контур (патч — файл, не PR), либо не их задача.
- **Потолок числа кругов, зашитый в промпт/конфиг.** kit-lite цитирует
  Superpowers: «Superpowers держит до пяти кругов, с четвёртого — свежий
  исполнитель на модели сильнее» (`kit-lite/roles/build.md:89`, вторично —
  сам текст SKILL.md эту цифру мне подтвердить не удалось, вижу только через
  цитату kit-lite). Сам kit-lite ограничивается двумя кругами из-за потолка
  диффа, дальше — `blocked` (`build.md:90-91`). Kandev сознательно круга не
  считает.

## Чего сознательно не кладут

- **Не трогать файлы/не коммитить/не пушить, если фидбек неактуален** —
  Kandev формулирует это дважды подряд, для pending- и non-actionable-веток:
  «do not modify files, do not commit, and do not push» (`ci-auto-fix.md:16`
  и `:21-22`, то же в `mr-auto-fix.md`).
- **Не мержить** — общее место у всех, кто вообще касается PR/MR (Kandev,
  CodeRabbit); у claude-security это доведено до предела — фикс даже не
  пушится, только патч-файл на диске для ручного применения.
- **Не делать широких рефакторов и «раз уж я здесь» правок** — сказано явно
  и в Kandev, и в обоих агентах claude-security (см. «Что кладут всегда»).
- **Не выносить вердикт о собственной работе** — claude-security категорично
  разносит генерацию и верификацию патча по разным агентам именно по этой
  причине.
- **Не быть просто советчиком, когда триггер — «CI упало» или «ревью
  запросило изменения».** Показательный контраст: `comment-analyzer` из
  pr-review-toolkit прямо пишет «IMPORTANT: You analyze and provide feedback
  only. Do not modify code or comments directly» (`comment-analyzer.md:79`) —
  но это роль другого класса (анализ качества комментариев по запросу), а не
  ответ на блокирующий CI/ревью. Ни один источник с ролью-фиксером,
  триггернутой именно провалом CI или запросом изменений, не оставляет её
  советчиком без права правки.

## Формат вывода

- **Kandev (`ci-auto-fix`/`mr-auto-fix`)** — не задаёт жёсткую структуру,
  свободный текст с обязательным содержанием, но оно ветвится по трём
  сценариям:
  1. Правки были: «summarize what changed and which verification commands
     you ran» (`ci-auto-fix.md:28`).
  2. Фидбек неактуален: «reply only with a short summary that there is
     nothing actionable to address» (`ci-auto-fix.md:19`).
  3. CI ещё крутится: «Reply that CI is still in progress and include the
     pending check names if they were provided» (`ci-auto-fix.md:23`).
- **claude-security** — жёсткая структурированная схема, а не проза:
  `patch-generator` возвращает `summary` (root cause + что делает фикс) и
  `changedFiles` (`patch-generator.md:35`); `patch-verifier` возвращает
  вердикт PASS/REJECT плюс три обязательных клейма (`TARGETED`,
  `NO_NEW_VULNERABILITY`, `BEHAVIOUR_UNCHANGED` — каждый `CONFIDENT` /
  `NOT_CONFIDENT` / `UNSURE` с однострочным доказательством), булево
  `untested`, точный список `REVIEWED_PATHS` и дословные `testsRun`
  (`patch-verifier.md:30-44`).
- **CodeRabbit Autofix** — вывод не текстовый отчёт, а материальный артефакт:
  либо прямой коммит в текущую ветку, либо отдельный stacked PR; при
  отсутствии валидных инструкций — сообщение, что фиксов не применено.
- **Superpowers** — ответы построчно в конкретный тред ревью-комментария, не
  единый сводный документ.

## Условие завершения

- **Kandev**: турн завершается одним из трёх взаимоисключающих исходов —
  фикс + сводка изменений и команд проверки; или короткий ответ «нечего
  чинить»; или ответ «CI ещё идёт» без опроса вхолостую («do not poll
  indefinitely», `ci-auto-fix.md:22`). Ни один из исходов не предполагает
  ожидания внутри самого турна.
- **claude-security**: пайплайн завершается вердиктом `patch-verifier`
  (PASS/REJECT) — «Return the structured verdict the dispatch requests…
  otherwise REJECT, with objections concrete enough for a fresh attempt to
  act on» (`patch-verifier.md:44`). Это единственный источник, где
  завершение роли явно означает «одна попытка — один явный проверяемый
  вердикт», а не просто «ответила текстом».
- **Superpowers**: завершено, когда «all feedback items are clarified... each
  fix is individually tested... no regressions... technical pushback is
  resolved» — «the completion signal is the code itself, not confirmation
  statements» (пересказ по `receiving-code-review/SKILL.md`).
- **kit-lite**: завершение роли естественное (правки внесены и описаны в
  `build-notes.md`), но у самого цикла ревью-фиксов есть внешний
  ограничитель — потолок кругов, после которого не «доделываем», а
  `blocked` (`build.md:91`).
- **Общее для всех источников с ролью-фиксером**: «нечего делать» —
  легитимный и явно описанный исход, а не ошибка или зависание (Kandev —
  прямым текстом; CodeRabbit — «skips execution and reports that no fixes
  were applied»).

## Расхождения и спорное

1. **Свежий контекст vs продолжение той же сессии.** Kandev сознательно
   сбрасывает контекст перед `Review Fixes` (`DEVELOPMENT-ROUTES.md:67-68,
   88-89` — «получают свежие контексты… поэтому не полагаются на самооценку
   автора»). kit-lite делает наоборот по умолчанию: «Первые круги — ревью,
   повтор после `NEEDS_TEST_FIX` — тот же исполнитель, если провайдер умеет
   продолжать подагента: контекст цел, он знает код и свои решения. Не умеет
   — новый исполнитель» (`build.md:87-89`) — то есть continuation выбран как
   основной путь, а сброс — только вынужденный fallback. Это прямое
   расхождение в философии, а не деталь: один источник считает независимость
   важнее стоимости повторного чтения, другой — наоборот.
2. **Кто проверяет фикс.** claude-security категорически не доверяет
   генератору патча собственную оценку и держит отдельного verifier-агента.
   Kandev в самом промпте `ci-auto-fix`/`mr-auto-fix` такого разделения не
   делает — роль сама фиксит и сама пишет отчёт; независимая проверка
   (`Final Verification`) по архитектуре Kandev смотрит на другое (полный
   прогон, не корректность конкретного фикса), и `DEVELOPMENT-ROUTES.md`
   прямо признаёт это как незакрытый вопрос: «после `Review Fixes`
   независимого повторного ревью нет» (строка 218).
3. **Правит код вообще, или только советует.** Большинство источников,
   триггернутых провалом CI/явным запросом изменений (Kandev, CodeRabbit,
   claude-security, Superpowers), считают правку кода обязанностью роли.
   Но там, где триггер — общий запрос на качество без «CI упало» (feature-dev
   Phase 6, pr-review-toolkit), решение сознательно отдают человеку:
   «Present findings to user and ask what they want to do (fix now, fix
   later, or proceed as-is)» (`feature-dev.md:108`). Это не противоречие по
   существу — скорее подтверждение, что наш триггер (два предыдущих ревью)
   ближе к первой группе, — но стоит иметь в виду как альтернативную модель.
4. **Потолок кругов.** Цифра «до пяти, с четвёртого — модель сильнее»
   существует только как цитата внутри kit-lite; я не смог подтвердить её
   прямо в `SKILL.md` Superpowers — источник вторичный. Кандев здесь занимает
   крайнюю позицию: круга вообще нет, ограничитель — только человек на доске
   (`DEVELOPMENT-ROUTES.md:226-227`), и это явно осознанный компромисс, а не
   недосмотр.

## Выводы для нас

**Стоит взять:**
- Гейт «сначала классифицируй actionable/non-actionable, потом действуй»
  Kandev уже использует в `ci-auto-fix`/`mr-auto-fix` — это совпадает с тем,
  что делают независимо ещё два источника (CodeRabbit, Superpowers), стоит
  сохранить и для `Review Fixes` как первую операцию промпта, а не только для
  auto-fix-ветки.
- Формулировку охвата у `patch-generator` стоит взять как более сильную, чем
  терпкая фраза «Preserve unrelated work and avoid broad refactors»: явный
  список запрещённого («no drive-by refactors, no formatting sweeps, no
  dependency bumps, no "while I'm here" fixes... even real ones») меньше
  оставляет на усмотрение модели.
- Дисциплину ответа в конкретный тред у Superpowers («reply in the comment
  thread, not as a top-level PR comment», без «Thanks for catching that!»)
  стоит взять как уточнение к тонкой фразе Kandev «reply to that thread with
  the fix summary» — у нас пока не сказано, что реплика должна быть
  технической, а не вежливой отпиской.
- Паттерн «когда решение не может принять сама роль — явно сказать это, а не
  промолчать» у `patch-generator`: «When a finding cannot be fixed without a
  decision only the owner can make, change nothing and say exactly that in
  `summary`» — у нас это особенно важно именно из-за незакрытого цикла
  ревью: если `Review Fixes` не подтверждает уверенность в исправлении,
  больше никто автоматически не перепроверит.

**Не стоит брать:**
- Отдельного `patch-verifier`-агента как второй роли внутри самого `Review
  Fixes` — эта работа по архитектуре Kandev уже закреплена за `Final
  Verification` (другой шаг, другой промпт); дублировать роль было бы
  избыточно, а не усилением независимости.
- Модель «патч не коммитится, только файл для ручного применения» у
  claude-security — она подразумевает другой процесс поставки (человек
  вручную применяет диф), тогда как весь маршрут Kandev рассчитан на прямой
  коммит/пуш в ветку задачи с последующим `Draft PR`.
- «Continuation той же сессии» из kit-lite — прямо противоречит уже принятому
  в `DEVELOPMENT-ROUTES.md` решению сбрасывать контекст перед этим шагом;
  это решено на уровне маршрута, а не промпта роли, менять не наш мандат.

**Чего в источниках нет, а нам нужно из-за особенностей Kandev:**
- Все найденные аналоги с ролью-фиксером получают фидбек из живого источника
  — PR/MR API, webhook о провале CI. У `Review Fixes` источник другой:
  файловые hand-off артефакты `code-review.md` и `security-review.md` внутри
  `.kandev/artifacts/<TASK_ID>/` (`DEVELOPMENT-ROUTES.md:140-141`), которые
  уже существуют к моменту старта шага. Значит ветка «CI ещё не готово, не
  опрашивать бесконечно» из `ci-auto-fix`/`mr-auto-fix`, скорее всего, вообще
  не нужна `Review Fixes` — находки уже статичны на входе; а вот сам факт
  чтения именно этих двух файлов и запись `review-fixes.md` — шаг, которого
  нет ни в одном источнике, его придётся написать с нуля.
- Ни один источник не работает в паре с шагом, который специально существует
  для того, чтобы «остаться пустым» и не потреблять токены зря
  (`DEVELOPMENT-ROUTES.md:158-159`: «Artifact создаётся только при
  содержательном результате; обязательные пустые файлы лишь расходуют токены
  и создают ложное ощущение завершённости») — у Kandev нужно явно прописать,
  что при пустом входе роль не создаёт `review-fixes.md` вовсе, а не пишет
  файл с текстом «нечего делать», в отличие от текстового «reply only with a
  short summary» у `ci-auto-fix`.
- Ни в одном источнике нет требования вызвать сигнал перехода (`
  step_complete_kandev`), который в Kandev обязателен для любого исхода —
  включая пустой (`DEVELOPMENT-ROUTES.md:102-103`). Это чисто наша
  инфраструктурная деталь, источники такого механизма не описывают вообще.
