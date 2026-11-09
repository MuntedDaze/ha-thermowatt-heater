FROM ghcr.io/home-assistant/base:3.24

# Install python and dependencies
RUN apk add --no-cache python3 py3-pip ca-certificates

# Install python libraries
COPY requirements.txt /requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /requirements.txt

ENV PYTHONUNBUFFERED=1
# Copy data for add-on
COPY run.sh /
COPY thermowatt_bridge.py thermowatt_read_only.py /

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
