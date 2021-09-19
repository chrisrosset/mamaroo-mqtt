FROM alpine:latest

RUN apk add --no-cache bluez python3 py3-pip

RUN mkdir /app
COPY . /app
WORKDIR "/app"

RUN yes | pip install -r requirements.txt

ENTRYPOINT ["python3", "mamaroo_mqtt.py"]
