# -*- coding: utf-8 -*-
"""
配置管理器
封装 config_overrides.json 的读写逻辑，提供安全的配置管理
配置项定义（CONFIG_SCHEMA）统一在 config.py 中维护
"""

import json
import shutil
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

from config import CONFIG_OVERRIDES_FILE, CONFIG_SCHEMA, CONFIG_ITEM_MAP


class ConfigManager:
    """配置管理器"""

    def __init__(self, config_file: Optional[Path] = None):
        self.config_file = config_file or CONFIG_OVERRIDES_FILE
        self.config_file.parent.mkdir(parents=True, exist_ok=True)

    def _backup_config(self) -> Optional[Path]:
        """备份当前配置到 config_history 子目录，只保留最近 max_backups 个"""
        if not self.config_file.exists():
            return None
        history_dir = self.config_file.parent / "config_history"
        history_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = history_dir / f"{self.config_file.stem}_backup_{timestamp}.json"
        shutil.copy2(self.config_file, backup_file)
        # 清理旧备份，只保留最近 max_backups 个（动态读取配置值）
        import config as _cfg
        max_backups = _cfg.MAX_BACKUPS
        backups = sorted(history_dir.glob(f"{self.config_file.stem}_backup_*.json"))
        if len(backups) > max_backups:
            for old in backups[:-max_backups]:
                old.unlink()
        return backup_file

    def load_config(self) -> Dict[str, Any]:
        """加载当前配置（包含当前生效值和默认值）"""
        overrides: Dict[str, Any] = {}
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    overrides = json.load(f)
            except Exception:
                pass

        # 返回完整配置（当前值 + 默认值）
        result: Dict[str, Any] = {}
        for item in CONFIG_SCHEMA:
            # 当前值优先级：覆盖值 > 默认值
            current_value = overrides.get(item.key, item.default)
            result[item.key] = {
                "label": item.label,
                "type": item.type,
                "current": current_value,
                "default": item.default,
                "min": item.min,
                "max": item.max,
                "description": item.description,
            }
        return result

    def save_config(self, new_config: Dict[str, Any]) -> Dict[str, Any]:
        """保存配置"""
        # 先备份
        self._backup_config()

        # 验证配置
        validated = self._validate_config(new_config)

        # 保存
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(validated, f, indent=2, ensure_ascii=False)

        return {"status": "success", "saved": validated}

    def _validate_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """验证配置项"""
        result: Dict[str, Any] = {}
        for key, value in config.items():
            item = CONFIG_ITEM_MAP.get(key)
            if not item:
                continue  # 忽略未知配置项

            # 类型转换
            try:
                if item.type == "int":
                    validated = int(value)
                elif item.type == "float":
                    validated = float(value)
                elif item.type == "bool":
                    validated = bool(value)
                elif item.type == "str":
                    validated = str(value)
                else:
                    validated = value
            except (ValueError, TypeError):
                validated = item.default

            # 范围校验
            if item.min is not None and validated < item.min:
                validated = item.min
            if item.max is not None and validated > item.max:
                validated = item.max

            result[key] = validated

        return result

    def reset_config(self) -> Dict[str, Any]:
        """恢复默认配置"""
        self._backup_config()
        if self.config_file.exists():
            self.config_file.unlink()
        return {"status": "success", "message": "配置已恢复默认"}


# 单例
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager
