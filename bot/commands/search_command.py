from services.movie_search_service import MovieSearchService


async def handle_search_command(chat_id: int, query: str):
    search_service = MovieSearchService()
    results = search_service.search(query)
    return format_search_results(results)


def format_search_results(results):
    return '\n'.join(f"{movie['title']} ({movie['year']})" for movie in results)
