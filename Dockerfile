# ============================================================================
# Backend Flask — imagem leve e executada como usuário não-root.
# ============================================================================
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Ferramentas de build mínimas para wheels sem binário pré-compilado
# (principalmente dependências cripto do ccxt).
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libffi-dev libssl-dev \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

# UID/GID 1000 por default: no Linux os volumes bind-mountados pertencem ao
# usuario do host, entao o processo nao-root precisa do mesmo dono para gravar.
#
# Windows/WSL2: diretorios montados de C:\ aparecem como root:root dentro da VM.
# O docker_start.bat define USER_UID=0/USER_GID=0 para evitar "permission denied"
# ao gravar em ./docker_data, ./docker_models, ./logs e ./simulation_reports.
ARG USER_UID=1000
ARG USER_GID=1000
RUN if [ "${USER_UID}" != "0" ]; then \
      groupadd --gid ${USER_GID} appuser \
      && useradd --uid ${USER_UID} --gid ${USER_GID} --no-create-home \
           --home-dir /app --shell /usr/sbin/nologin appuser; \
    fi \
 && mkdir -p /app/data /app/models /app/logs /app/reports /app/simulation_reports \
 && chown -R ${USER_UID}:${USER_GID} /app \
 && chmod -R 775 /app/data /app/models /app/logs /app/reports /app/simulation_reports

# USER numerico funciona tanto para appuser (Linux) quanto para root (Windows).
USER ${USER_UID}:${USER_GID}

EXPOSE 5000

# O healthcheck usa urllib (já na stdlib) para não exigir curl na imagem.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/api/status', timeout=3).status == 200 else 1)" || exit 1

CMD ["python", "app.py"]
