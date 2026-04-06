FROM python:3.12-slim

WORKDIR /app

COPY . user_agent/
WORKDIR /app/user_agent

RUN if [ -f requirements.txt ]; then \
        pip install --no-cache-dir -r requirements.txt; \
    else \
        echo "No requirements.txt found"; \
    fi

EXPOSE 8088

CMD bash -c '\
  if [ -f /etc/ssl/certs/adc-egress-proxy-ca.crt ]; then \
    cat /etc/ssl/certs/adc-egress-proxy-ca.crt >> /etc/ssl/certs/ca-certificates.crt 2>/dev/null || true; \
    (cat /etc/ssl/certs/adc-egress-proxy-ca.crt >> /usr/local/lib/python3.12/site-packages/certifi/cacert.pem) 2>/dev/null || true; \
  fi && \
  python main.py'
