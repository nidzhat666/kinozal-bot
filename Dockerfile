FROM python:3.12

WORKDIR /usr/src/app

COPY . .

RUN pip install pipenv

RUN pipenv install --deploy --ignore-pipfile

ENV PYTHONPATH /usr/src/app/src

WORKDIR /usr/src/app/src

CMD ["pipenv", "run", "python", "bot/main.py"]
