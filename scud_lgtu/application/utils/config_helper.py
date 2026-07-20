"""
Утилитарные функции для работы с конфигурацией устройств.

Функции
-------
- find_device_config: найти конфигурацию устройства по label
"""
from typing import Optional, Dict, Any


def find_device_config(devices: dict, device_type: str, label: str) -> Optional[Dict[str, Any]]:
    """
    Найти конфигурацию устройства по label.

    Parameters
    ----------
    devices : dict
        Словарь устройств из конфига
    device_type : str
        Тип устройства (readers, buttons, sensors)
    label : str
        Имя устройства для поиска

    Returns
    -------
    dict or None
        Конфигурация устройства или None если не найден
    """
    devices_of_type = devices.get(device_type, {})
    for device_name, device_config in devices_of_type.items():
        if device_config.get("label") == label:
            return device_config
    return None
