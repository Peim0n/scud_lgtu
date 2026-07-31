# Деплой проекта SCUD LGTU на Orange Pi

Инструкция по настройке git для обновления кода системы СКУД на Orange Pi с компьютера разработчика без использования SFTP.

## Описание проекта

SCUD LGTU - система контроля доступа с турникетом, реализующая чистую архитектуру с разделением на доменный слой, слой приложения и инфраструктурный слой.

## Репозитории

- **origin**: https://github.com/Peim0n/scud_lgtu (основной репозиторий)
- **orangepi**: root@172.19.12.202:/opt/scud_lgtu.git (деплой на устройство)
- **hq**: git@git.hq.int-sys.ru:project/alo-acs-max-26.git (корпоративный репозиторий, ветка lgtu-acs-25)

## Настройка на Orange Pi

### 1. Настройка алиаса sudovenv

Добавьте алиас в `.bashrc` пользователя orangepi:

```bash
ssh orangepi@orangepi
nano ~/.bashrc
```

Добавьте в конец файла:

```bash
# Алиас для запуска с venv и sudo (для GPIO)
alias sudovenv='sudo .venv/bin/python3'
```

Примените изменения:

```bash
source ~/.bashrc
```

### 2. Инициализация git репозитория

```bash
ssh root@orangepi
cd /opt/scud_lgtu
git init
git add .
git commit -m "Initial commit"
```

### 3. Создание bare репозитория

Создайте bare репозиторий для приёма изменений:

```bash
cd /opt
git clone --bare scud_lgtu scud_lgtu.git
```

### 4. Настройка post-receive hook

Создайте хук для автоматического обновления рабочего каталога:

```bash
nano /opt/scud_lgtu.git/hooks/post-receive
```

Содержимое:

```bash
#!/bin/bash
cd /opt/scud_lgtu
git --git-dir=/opt/scud_lgtu/.git --work-tree=/opt/scud_lgtu checkout -f
```

Сделайте хук исполняемым:

```bash
chmod +x /opt/scud_lgtu.git/hooks/post-receive
```

### 5. Настройка прав доступа

Добавьте пользователя orangepi в группу sudo для работы с GPIO:

```bash
ssh root@orangepi
usermod -aG sudo orangepi
```

Настройте sudo без пароля для Python с venv:

```bash
sudo visudo
```

Добавьте строку:

### 6. Установка зависимостей для QR кодов

Для работы QR кодов требуется модуль cryptography. Установите его в виртуальное окружение:

```bash
# Активируйте виртуальное окружение
source /opt/scud_lgtu/venv/bin/activate

# Установите cryptography
pip install cryptography

# Или через apt (если доступен пакет)
sudo apt install python3-cryptography
```

```
orangepi ALL=(ALL) NOPASSWD: /opt/scud_lgtu/.venv/bin/python3
```

### 6. Создание venv

```bash
cd /opt/scud_lgtu
python3 -m venv .venv
source .venv/bin/activate
pip install gpiod pyserial pyyaml
```

## Настройка на компьютере разработчика

### 1. Добавление удалённых репозиториев

```bash
cd /home/danil/Git/scud_lgtu
git remote add orangepi root@172.19.12.202:/opt/scud_lgtu.git
git remote add hq git@git.hq.int-sys.ru:project/alo-acs-max-26.git
```

### 2. Отправка изменений на Orange Pi

```bash
git add .
git commit -m "Описание изменений"
git push orangepi master
```

### 3. Отправка изменений в корпоративный репозиторий

```bash
git checkout lgtu-acs-25
git add .
git commit -m "Описание изменений"
git push hq lgtu-acs-25
git checkout master
```

### 4. Обновление на Orange Pi

После push изменения автоматически применятся в `/opt/scud_lgtu` благодаря post-receive hook.

### 5. Перезапуск сервиса (если нужно)

```bash
ssh root@orangepi
systemctl restart scud_lgtu
```

## Альтернативный вариант через SSH ключи

### 1. Генерация SSH ключа на компьютере разработчика

```bash
ssh-keygen -t ed25519 -C "danil@dev-pc"
```

### 2. Копирование ключа на Orange Pi

```bash
ssh-copy-id root@orangepi
```

### 3. Настройка git config

```bash
git config remote.orangepi.url root@orangepi:/opt/scud_lgtu.git
```

## Скрипты для быстрого деплоя

### Деплой на Orange Pi

Создайте скрипт `deploy_orangepi.sh` на компьютере разработчика:

```bash
#!/bin/bash
cd /home/danil/Git/scud_lgtu
git add .
git commit -m "$1"
git push orangepi master
ssh root@orangepi "systemctl restart scud_lgtu"
```

Использование:

```bash
./deploy_orangepi.sh "Описание изменений"
```

### Деплой в корпоративный репозиторий

Создайте скрипт `deploy_hq.sh` на компьютере разработчика:

```bash
#!/bin/bash
cd /home/danil/Git/scud_lgtu
git checkout lgtu-acs-25
git add .
git commit -m "$1"
git push hq lgtu-acs-25
git checkout master
```

Использование:

```bash
./deploy_hq.sh "Описание изменений"
```

## Проверка

Проверьте, что всё работает:

```bash
# На компьютере разработчика
echo "test" > test.txt
git add test.txt
git commit -m "Test deployment"
git push orangepi master

# На Orange Pi
ssh root@orangepi
cat /opt/scud_lgtu/test.txt
```
