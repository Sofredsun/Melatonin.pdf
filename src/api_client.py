import os
from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()


def call_llm(messages, model=None, temperature=None):

    api_key = os.getenv("DEFAULT_API_KEY")
    base_url = os.getenv("DEFAULT_BASE_URL")
    model_name = model or os.getenv("DEFAULT_MODEL", "gpt-4o-mini")
    temp = temperature if temperature is not None else float(os.getenv("TEMPERATURE", 0.0))

    client = OpenAI(api_key=api_key, base_url=base_url)
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=temp,
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Ошибка API: {e}")
        return None
