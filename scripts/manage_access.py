#!/usr/bin/env python3
"""
Управление локальным кэшем разрешённых идентификаторов.

Примеры:
  python scripts/manage_access.py -p local_access.json add maxid 12345
  python scripts/manage_access.py -p local_access.json add cardid 11223344
  python scripts/manage_access.py -p local_access.json list
  python scripts/manage_access.py -p local_access.json remove maxid 12345
"""

import argparse
import sys

sys.path.insert(0, "/home/danil/Git/scud_lgtu")

from scud_lgtu.local_access_cache import LocalAccessCache


def main() -> None:
    """CLI для управления локальным кэшем идентификаторов."""
    parser = argparse.ArgumentParser(description="Управление local_access.json")
    parser.add_argument("-p", "--path", type=str, default="local_access.json", help="Путь к JSON-файлу")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Добавить идентификатор")
    add_parser.add_argument("type", choices=["maxid", "cardid"], help="Тип идентификатора")
    add_parser.add_argument("token", help="Значение идентификатора")
    add_parser.add_argument("--user-id", type=int, default=None, help="ID пользователя")

    remove_parser = subparsers.add_parser("remove", help="Удалить идентификатор")
    remove_parser.add_argument("type", choices=["maxid", "cardid"], help="Тип идентификатора")
    remove_parser.add_argument("token", help="Значение идентификатора")

    list_parser = subparsers.add_parser("list", help="Показать кэш")

    args = parser.parse_args()

    cache = LocalAccessCache(path=args.path)

    if args.command == "add":
        cache.add(args.type, args.token, user_id=args.user_id)
        print(f"Добавлен {args.type}={args.token} user_id={args.user_id}")
    elif args.command == "remove":
        cache._allowed.setdefault(args.type, set()).discard(
            cache._hash(args.type, args.token)
        )
        cache.save_json(args.path)
        print(f"Удалён {args.type}={args.token}")
    elif args.command == "list":
        print("Локальный кэш доступа:")
        for id_type, values in cache._allowed.items():
            print(f"  {id_type}: {sorted(values)}")
        print("Пользователи:")
        for uid, tokens in cache._users.items():
            print(f"  user_id={uid}: {tokens}")


if __name__ == "__main__":
    main()
