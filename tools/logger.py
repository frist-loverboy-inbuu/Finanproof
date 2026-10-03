import json
import uuid
from datetime import datetime
from pathlib import Path


class AuditLogger:
    def __init__(self, log_dir: str | Path = "logs", run_id: str | None = None):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or f"run_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
        self.path = self.log_dir / f"{self.run_id}.jsonl"

    def log(self, step: str, tool: str | None = None, input=None, output=None,
            tool_version: str = "v1.0", **extra) -> dict:
        record = {
            "run_id": self.run_id,
            "step": step,
            "tool": tool,
            "input": input,
            "output": output,
            "tool_version": tool_version,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        record.update(extra)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return record

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


if __name__ == "__main__":
    logger = AuditLogger()
    logger.log(
        "calculate_growth_rate",
        tool="calc",
        input={"current": 98.6, "previous": 82.2},
        output={"growth_rate": 19.95, "rounded": 20.0},
    )
    print(logger.path)
    print(json.dumps(logger.read_all(), ensure_ascii=False, indent=2))
