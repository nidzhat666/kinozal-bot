import json

from groq import AsyncGroq
from groq.types.chat import ChatCompletionSystemMessageParam
from jinja2 import Environment, FileSystemLoader

from bot import config
from bot.config import TEMPLATES_DIR
from custom_types.movie_detail_service_types import AudioLanguage, MovieDetails

client = AsyncGroq(
    api_key=config.GROQ_API_KEY
)

async def get_movie_search_result(movie_detail: MovieDetails, **kwargs) -> MovieDetails | None:
    prompt = get_movie_search_prompt(**kwargs)
    chat_completion = await client.chat.completions.create(
        messages=[
            ChatCompletionSystemMessageParam(
                content=prompt,
                role="system",
            ),
        ],
        model="openai/gpt-oss-120b",
    )
    response = chat_completion.choices[0].message.content
    json_response = json.loads(response)
    if not json_response.get("is_valid"):
        return None

    movie_detail.video_quality = json_response.get("video_quality")
    movie_detail.audio_quality = json_response.get("audio_quality")
    audio_language = [AudioLanguage(**lang) for lang in json_response.get("audio_language", [])]
    movie_detail.audio_language = audio_language
    return movie_detail


def get_movie_search_prompt(title: str, body: str,
                            requested: str, requested_type: str,
                            **kwargs) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    template = env.get_template("movie_search_prompt.j2")

    return template.render(title=title, body=body,
                                      requested=requested, requested_type=requested_type,
                                      **kwargs)


# if __name__ == '__main__':
#     import asyncio
#     asyncio.run(get_movie_search_result(
#
#     ))