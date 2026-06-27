import os
import logging
import importlib.util
from pathlib import Path
from typing import Optional

from openai import OpenAI

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


logger = logging.getLogger(__name__)


class VseGPTClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("VSEGPT_API_KEY")

        if not self.api_key:
            raise ValueError("Не найден VSEGPT_API_KEY")

        self.default_model = (
            default_model
            or os.getenv("VSEGPT_MODEL")
            or "anthropic/claude-3-haiku"
        )

        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.vsegpt.ru/v1",
            timeout=120,
            max_retries=2,
        )

    def call_api(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        context: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 3000,
    ) -> str:

        model_to_use = model or self.default_model

        messages = []

        if system_prompt:
            messages.append(
                {
                    "role": "system",
                    "content": system_prompt,
                }
            )

        if context:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Контекст для анализа:\n\n"
                        f"{context}"
                    ),
                }
            )

        messages.append(
            {
                "role": "user",
                "content": prompt,
            }
        )

        params = {
            "model": model_to_use,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            response = self.client.chat.completions.create(
                **params
            )

            if not response.choices:
                raise RuntimeError(
                    "Модель вернула пустой ответ"
                )

            content = (
                response
                .choices[0]
                .message
                .content
            )

            if content is None:
                raise RuntimeError("Ответ модели пуст")

            return content

        except Exception:
            logger.exception("Ошибка вызова API")
            raise


def load_prompt_module(
    prompt_module_name: str,
    prompts_dir: Optional[str] = None,
):

    if prompts_dir is None:
        prompts_dir = (Path(__file__).resolve().parent.parent / "external" / "chemx" / "prompts")

    path = (Path(prompts_dir) / f"{prompt_module_name}.py")

    if not path.exists():
        raise FileNotFoundError(f"Промпт не найден:\n{path}")

    spec = importlib.util.spec_from_file_location(prompt_module_name, str(path),)

    if spec is None or spec.loader is None:
        raise ImportError(f"Не удалось загрузить {path}")

    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    return module


def call_with_prompt(
    client: VseGPTClient,
    prompt_module_name: str,
    context: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 20000,
    prompts_dir: Optional[str] = None,
):

    module = load_prompt_module(
        prompt_module_name,
        prompts_dir,
    )

    instructions = getattr(
        module,
        "INSTRUCTIONS",
        None,
    )

    prompt = getattr(
        module,
        "PROMPT",
        None,
    )

    if prompt is None:
        raise ValueError(
            f"{prompt_module_name}: "
            "не найден PROMPT"
        )

    return client.call_api(
        prompt=prompt,
        system_prompt=instructions,
        context=context,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO
    )

    client = VseGPTClient()

    print(
        "Модель:",
        client.default_model,
    )

    result = client.call_api(
        prompt="Напиши числа от 1 до 10"
    )

    print(result)
