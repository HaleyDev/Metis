from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any

import yaml


class YamlConfig:
	_instance: "YamlConfig | None" = None
	_instance_lock = Lock()

	def __new__(cls, file_path: str | Path | None = None) -> "YamlConfig":
		if cls._instance is None:
			with cls._instance_lock:
				if cls._instance is None:
					cls._instance = super().__new__(cls)
		return cls._instance

	def __init__(self, file_path: str | Path | None = None) -> None:
		if getattr(self, "_initialized", False):
			if file_path is not None and Path(file_path) != self._file_path:
				self._file_path = Path(file_path)
				self.reload()
			return

		self._file_path = Path(file_path) if file_path else Path(__file__).with_name("config.yaml")
		self._config: dict[str, Any] = {}
		self.reload()
		self._initialized = True

	def reload(self) -> dict[str, Any]:
		if not self._file_path.exists():
			raise FileNotFoundError(f"YAML config file not found: {self._file_path}")

		with self._file_path.open("r", encoding="utf-8") as file:
			data = yaml.safe_load(file) or {}

		if not isinstance(data, dict):
			raise ValueError("YAML config content must be a mapping")

		self._config = data
		return self._config

	def get(self, key: str, default: Any = None) -> Any:
		return self._config.get(key, default)

	def all(self) -> dict[str, Any]:
		return dict(self._config)


config = YamlConfig()