FROM python:3.12

WORKDIR /usr/src/app

COPY . .

RUN pip install pipenv

RUN pipenv install --deploy --ignore-pipfile

WORKDIR /usr/src/app/src

ENV PYTHONPATH=/usr/src/app/src

CMD ["pipenv", "run", "python", "bot/main.py"]
