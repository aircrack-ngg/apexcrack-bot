FROM python:3.11-slim
WORKDIR /app
RUN apt update && apt install -y aircrack-ng hashcat hcxtools && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/data/{captures,wordlists,reports,scans}
CMD ["python", "bot.py"]
