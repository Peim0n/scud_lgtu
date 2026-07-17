#!/usr/bin/env python3
"""
Клиент для отправки команд симуляции в работающую систему.

Использование:
    python emulator_client.py card 1234567890 Wiegand-1
    python emulator_client.py qr https://example.com /dev/ttyS1
"""
import socket
import json
import sys

def send_command(host: str, port: int, command: dict):
    """Отправить команду на UDP сервер."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        data = json.dumps(command).encode('utf-8')
        sock.sendto(data, (host, port))
        print(f"Команда отправлена: {command}")
    finally:
        sock.close()

def main():
    if len(sys.argv) < 2:
        print("Использование:")
        print("  Симуляция карты: python emulator_client.py card <uid> <reader_id>")
        print("  Симуляция QR:    python emulator_client.py qr <data> <port>")
        print()
        print("Примеры:")
        print("  python emulator_client.py card 1234567890 Wiegand-1")
        print("  python emulator_client.py qr https://pass.lipetsk.ru/123 /dev/ttyS1")
        sys.exit(1)

    cmd_type = sys.argv[1].lower()
    host = "127.0.0.1"
    port = 9999

    if cmd_type == "card":
        if len(sys.argv) < 4:
            print("Ошибка: для карты нужны uid и reader_id")
            sys.exit(1)
        card_uid = sys.argv[2]
        reader_id = sys.argv[3]
        command = {"cmd": "card", "card_uid": card_uid, "reader_id": reader_id}
    elif cmd_type == "qr":
        if len(sys.argv) < 4:
            print("Ошибка: для QR нужны данные и порт")
            sys.exit(1)
        qr_data = sys.argv[2]
        port_name = sys.argv[3]
        command = {"cmd": "qr", "qr_data": qr_data, "port": port_name}
    else:
        print(f"Неизвестная команда: {cmd_type}")
        sys.exit(1)

    send_command(host, port, command)

if __name__ == "__main__":
    main()
