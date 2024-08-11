FROM python:3.12

WORKDIR /usr/src/app

COPY Pipfile ./

RUN pip install pipenv

RUN pipenv lock --clear

RUN pipenv install --deploy --system

COPY . .

ENV PYTHONPATH=/usr/src/app/src

WORKDIR /usr/src/app/src

CMD ["python", "bot/main.py"]
