"""Request dialects for research providers; coding benchmark config is unchanged."""

from dataclasses import dataclass
from mini_harness.config import Config


@dataclass(frozen=True)
class ResearchConfig(Config):
    disable_thinking: bool = False

    def request_options(self, sub=False):
        if self.provider in {"compatible", "codex"}:
            options = {
                "model": self.model_sub if sub else self.model_main,
                "max_tokens": self.max_tokens_sub if sub else self.max_tokens_main,
                "temperature": self.temp_set,
            }
            if self.provider == "compatible" and self.disable_thinking:
                options["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
            return options
        return super().request_options(sub)

    def request_messages(self, messages):
        return [
            {k: v for k, v in m.items() if k not in {"reasoning_content", "annotations", "parsed"}}
            for m in messages
        ]
