# Управление сервером разработки.
#
#   make apply   применить настройку. Сама разберётся, свежая машина или нет
#   make check   показать, что изменится, ничего не трогая
#   make audit   проверить снаружи: наружу не должно отвечать ничего
#   make ssh     зайти на сервер
#
# Машины перечислены в servers.yml. Если их больше одной, команда спросит,
# с какой работать. Чтобы не спрашивала: make apply h=имя-машины
#
# Сами команды живут в scripts/, а не здесь. Причина: рецепт make — это одна
# строка для оболочки, склеенная обратными слешами, и в ней нет ни set -e,
# ни номеров строк в ошибках, ни возможности проверить кусок отдельно.
#
# Ansible запускается в контейнере: на твоей машине ничего не ставится,
# а версия инструмента одинакова у всех и не зависит от того, что установлено.

.DEFAULT_GOAL := help
SHELL := /bin/bash

ANSIBLE_IMAGE := vps-dev-ansible

.PHONY: help
help:
	@awk 'BEGIN {FS = ":.*?## "} \
		/^##@/ {printf "\n  \033[1m%s\033[0m\n", substr($$0, 5)} \
		/^[a-zA-Z_-]+:.*?## / {printf "    \033[36m%-14s\033[0m %s\n", $$1, $$2}' \
		$(MAKEFILE_LIST)
	@echo ""

##@ Настройка

.PHONY: new
new: image ## Завести новую машину: h=имя ip=адрес [prov=Hetzner hw="CX32, 4 ядра"]
	@scripts/new.sh "$(h)" "$(ip)" "$(prov)" "$(hw)"

.PHONY: apply
apply: image ## Применить настройку. h=имя — одна машина, t=base — часть настройки
	@scripts/run-playbook.sh $(if $(h),--host $(h)) $(if $(t),--tags $(t))

.PHONY: check
check: image ## Что изменится. Ничего не трогает, заодно проверяет код
	@scripts/lint.sh
	@scripts/run-playbook.sh --check $(if $(h),--host $(h)) $(if $(t),--tags $(t))

##@ Проверка и доступ

.PHONY: servers
servers: image ## Показать реестр машин: имена, адреса, железо
	@scripts/servers.sh

.PHONY: watch
watch: image ## Присмотр: отвечают ли машины, есть ли место, всё ли работает
	@scripts/watch.sh $(h)

.PHONY: audit
audit: image ## Проверить снаружи: наружу не должно отвечать ничего. full=1 — весь диапазон
	@scripts/audit.sh $(h) $(if $(full),--full)

.PHONY: ping
ping: image ## Быстро проверить, что сервер отвечает
	@scripts/ping.sh $(h)

.PHONY: ssh
ssh: image ## Зайти на сервер
	@scripts/ssh.sh $(h)

.PHONY: reboot
reboot: image ## Перезагрузить машину и дождаться возвращения
	@scripts/reboot.sh $(h)

##@ Служебное

.PHONY: image
image: ## Собрать образ с Ansible, если его ещё нет
	@docker image inspect $(ANSIBLE_IMAGE) >/dev/null 2>&1 \
		|| docker build -t $(ANSIBLE_IMAGE) -f runner/Dockerfile .

.PHONY: rebuild-image
rebuild-image: ## Пересобрать образ после правки runner/
	@docker build --no-cache -t $(ANSIBLE_IMAGE) -f runner/Dockerfile .

.PHONY: lint
lint: image ## Проверить код настройки
	@scripts/lint.sh

.PHONY: trust
trust: image ## Заново запомнить ключ пересозданной машины
	@scripts/trust.sh $(h)

.PHONY: facts
facts: image ## Показать, что Ansible знает о машине
	@scripts/facts.sh $(h)
