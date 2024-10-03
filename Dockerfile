FROM archlinux:latest

RUN pacman -Syu --noconfirm && \
    pacman -S --noconfirm \
    firefox \
    geckodriver \
    python

RUN pacman -Scc --noconfirm

WORKDIR /app

COPY requirements.txt .

RUN python -m venv .venv

RUN .venv/bin/pip install --no-cache-dir -r requirements.txt

COPY archiver.py .
COPY cookies/ .
RUN touch text.txt

CMD [".venv/bin/python", "archiver.py"]