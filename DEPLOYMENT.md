# Настройка обновления через Git

Инструкция по настройке git для обновления кода на Orange Pi с компьютера разработчика без использования SFTP.

## Настройка на Orange Pi

### 1. Инициализация git репозитория

```bash
ssh root@orangepi
cd /opt/scud_lgtu
git init
git add .
git commit -m "Initial commit"
```

### 2. Создание bare репозитория

Создайте bare репозиторий для приёма изменений:

```bash
cd /opt
git clone --bare scud_lgtu scud_lgtu.git
```

### 3. Настройка post-receive hook

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

## Настройка на компьютере разработчика

### 1. Добавление удалённого репозитория

```bash
cd /home/danil/Git/scud_lgtu_refactor
git remote add orangepi root@orangepi:/opt/scud_lgtu.git
```

### 2. Отправка изменений на Orange Pi

```bash
git add .
git commit -m "Описание изменений"
git push orangepi master
```

### 3. Обновление на Orange Pi

После push изменения автоматически применятся в `/opt/scud_lgtu` благодаря post-receive hook.

### 4. Перезапуск сервиса (если нужно)

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

## Скрипт для быстрого деплоя

Создайте скрипт `deploy.sh` на компьютере разработчика:

```bash
#!/bin/bash
cd /home/danil/Git/scud_lgtu_refactor
git add .
git commit -m "$1"
git push orangepi master
ssh root@orangepi "systemctl restart scud_lgtu"
```

Использование:

```bash
./deploy.sh "Описание изменений"
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
