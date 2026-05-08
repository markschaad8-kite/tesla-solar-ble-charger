FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=America/New_York

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN if [ -s /app/requirements.txt ]; then pip3 install --no-cache-dir --break-system-packages -r /app/requirements.txt; fi

COPY solar_charger_twc.py /app/solar_charger.py

CMD ["python3", "/app/solar_charger.py"]
