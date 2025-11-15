import json
import asyncio
import logging

from groq import AsyncGroq
from groq.types.chat import ChatCompletionSystemMessageParam
from jinja2 import Environment, FileSystemLoader

from bot import config
from bot.config import TEMPLATES_DIR
from models.movie_detail_service_types import AudioLanguage, MovieDetails

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
        model="openai/gpt-oss-20b",
    )
    response = chat_completion.choices[0].message.content
    json_response = json.loads(response)
    if not json_response.get("is_valid"):
        return None

    movie_detail.video_quality = json_response.get("video_quality")
    movie_detail.audio_quality = json_response.get("audio_quality")
    audio_language = [AudioLanguage(**lang) for lang in json_response.get("audio_language", [])]
    movie_detail.audio_language = audio_language
    movie_detail.search_name = json_response.get("name")
    return movie_detail


async def filter_movies_with_groq(
    movies: list,
    *,
    requested_item: str,
    requested_type: str,
) -> list:
    movies_to_validate = [
        movie for movie in movies if (movie.search_name or movie.name)
    ]
    if not movies_to_validate:
        return []

    validation_tasks = [
        _validate_movie_with_groq(movie, requested_item, requested_type)
        for movie in movies_to_validate
    ]
    validation_results = await asyncio.gather(
        *validation_tasks,
        return_exceptions=True,
    )

    filtered: list = []
    for movie, validation in zip(movies_to_validate, validation_results):
        if isinstance(validation, Exception):
            logging.warning(
                "Groq validation raised for movie id %s: %s",
                movie.id,
                validation,
            )
            continue
        if validation is not None:
            filtered.append(validation)
        else:
            logging.warning("Groq validation failed for movie title %s", movie.name)

    logging.debug(
        "Groq validation filtered %d/%d results",
        len(filtered),
        len(movies_to_validate),
    )
    return filtered


async def _validate_movie_with_groq(
    movie: MovieDetails,
    requested_item: str,
    requested_type: str,
) -> MovieDetails | None:
    title = movie.search_name or movie.name
    if not title:
        return None

    try:
        validation = await get_movie_search_result(
            movie,
            title=title,
            requested_item=requested_item,
            requested_type=requested_type,
        )
    except Exception as exc:
        logging.warning(
            "Groq validation failed for movie id %s (%s): %s",
            movie.id,
            title,
            exc,
        )
        return None

    return validation


def get_movie_search_prompt(
    title: str, requested_item: str, requested_type: str, **kwargs
) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    template = env.get_template("movie_search_prompt.j2")

    return template.render(
        title=title,
        requested_item=requested_item,
        requested_type=requested_type,
        **kwargs,
    )

