-- Нужен ли задаче стенд и в какой сессии его поднимает роль «Стенд».
-- Флаг ставит владелец в разговоре с мастером; сессия заводится на первых
-- воротах или по кнопке — тогда, когда владелец приходит смотреть работу.
ALTER TABLE task ADD COLUMN stand_wanted INTEGER NOT NULL DEFAULT 0;
ALTER TABLE task ADD COLUMN stand_session TEXT;
