-- Стенд задачи: имя арендатора блока портов и порт, на который идти смотреть.
-- Пусто — стенд не поднимали. Номера выдаёт `ports`, движок только помнит
-- имя, чтобы погасить и вернуть блок при закрытии задачи.
ALTER TABLE task ADD COLUMN stand TEXT;
ALTER TABLE task ADD COLUMN stand_port INTEGER;
