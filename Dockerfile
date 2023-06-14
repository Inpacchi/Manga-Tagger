FROM python:3.11.4-alpine3.18
LABEL authors="sanchoblaze <me@sanchoblaze.com>"

RUN apk add gcc python3-dev python3-tkinter build-base linux-headers git
RUN python -m pip install --upgrade pip

RUN mkdir /downloads
RUN mkdir /library
RUN mkdir /config
RUN mkdir /manga-tagger

# COPY settings.json /manga-tagger/
COPY MangaTaggerLib /manga-tagger/MangaTaggerLib
COPY MangaTagger.py /manga-tagger/
COPY requirements.txt /manga-tagger/

VOLUME /downloads
VOLUME /library
VOLUME /config

WORKDIR /manga-tagger/

RUN pip install --no-cache -r requirements.txt

RUN python MangaTagger.py