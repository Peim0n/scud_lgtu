#!/bin/bash
# Настройка read-only системы на OrangePi.
# Логи и временные файлы — в RAM (tmpfs).
# Настройки и сертификаты — на отдельном разделе (mmcblk0p3).
# Код — на /srv (уже ro).
#
# Запускать: bash setup-ro-system.sh
#
# ВНИМАНИЕ: после применения / станет read-only.
# Для записи: mount -o remount,rw /
# Откат: mount -o remount,rw / и вернуть fstab.

set -e

echo "=== 1. Смонтировать mmcblk0p3 и перенести /etc/scud_lgtu ==="

# Смонтировать временно
mkdir -p /mnt/data
mount /dev/mmcblk0p3 /mnt/data

# Создать структуру на новом разделе
mkdir -p /mnt/data/scud_lgtu/certs

# Скопировать текущие данные
cp -a /etc/scud_lgtu/* /mnt/data/scud_lgtu/ 2>/dev/null || true

echo "=== 2. Добавить mmcblk0p3 в fstab ==="

# Добавить запись в fstab (если ещё нет)
if ! grep -q "mmcblk0p3" /etc/fstab; then
    echo "UUID=7dcba740-3f2d-4610-b0f5-8f74a1855e15 /etc/scud_lgtu ext4 rw,noatime 0 2" >> /etc/fstab
fi

echo "=== 3. Добавить tmpfs для /var/log, /var/tmp, /var/cache ==="

# Добавить tmpfs записи (если ещё нет)
if ! grep -q "tmpfs.*var/log" /etc/fstab; then
    cat >> /etc/fstab << 'TMPFS'

# ── Read-only system: временные каталоги в RAM ──
tmpfs /var/log      tmpfs defaults,noatime,size=64M,mode=1777 0 0
tmpfs /var/tmp      tmpfs defaults,noatime,size=16M,mode=1777 0 0
tmpfs /var/cache    tmpfs defaults,noatime,size=64M,mode=755  0 0
tmpfs /var/lib/dhcp tmpfs defaults,noatime,size=4M,mode=755   0 0
tmpfs /var/lib/networkmanager tmpfs defaults,noatime,size=4M,mode=755 0 0
TMPFS
fi

echo "=== 4. Настроить journald: логи только в RAM ==="

# Storage=volatile — логи в RAM, не на диск
sed -i 's/^#Storage=auto/Storage=volatile/' /etc/systemd/journald.conf
# Если не было такой строки — добавить
if ! grep -q "^Storage=volatile" /etc/systemd/journald.conf; then
    sed -i 's/^#Storage=.*/Storage=volatile/' /etc/systemd/journald.conf
fi
# Лимит размера логов в RAM (64 МБ)
if ! grep -q "^SystemMaxUse" /etc/systemd/journald.conf; then
    sed -i '/^\[Journal\]/a SystemMaxUse=64M' /etc/systemd/journald.conf
fi

echo "=== 5. Сделать / read-only в fstab ==="

# Заменить defaults на ro для корневого раздела
sed -i 's|^\(UUID=98dab596.* / ext4 \)defaults,noatime,commit=120|\1ro,noatime|' /etc/fstab

echo "=== 6. Отключить swap на zram (опционально, экономит RAM) ==="
# Оставляем — swap полезен для предотвращения OOM

echo "=== 7. Проверка fstab ==="
echo "--- /etc/fstab ---"
cat /etc/fstab
echo ""

echo "=== 8. Проверка journald.conf ==="
grep -E "^Storage|^SystemMaxUse" /etc/systemd/journald.conf
echo ""

echo "=== 9. Размонтировать временный mount ==="
umount /mnt/data
rmdir /mnt/data 2>/dev/null || true

echo ""
echo "========================================"
echo "Настройка завершена. Проверьте fstab выше."
echo ""
echo "Для применения:"
echo "  1. Остановить сервисы: systemctl stop scud_lgtu scud_lgtu_web"
echo "  2. Перезагрузить: reboot"
echo "  3. После перезагрузки / будет ro, /etc/scud_lgtu — rw на p3"
echo ""
echo "Для записи на / (обновление пакетов и т.д.):"
echo "  mount -o remount,rw /"
echo ""
echo "Откат (вернуть rw на /):"
echo "  mount -o remount,rw /"
echo "  sed -i 's|ro,noatime|defaults,noatime,commit=120|' /etc/fstab"
echo "========================================"
