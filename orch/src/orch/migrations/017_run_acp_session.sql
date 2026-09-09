-- uuid сессии Claude Code для захода: имя файла транскрипта
-- (`~/.claude/projects/<путь>/<uuid>.jsonl`). У AoE свой id сессии, и без
-- этой связи скелет хода склеивался из чужих транскриптов, а признак жизни
-- роли брать было неоткуда.
ALTER TABLE run ADD COLUMN acp_session_id TEXT;
