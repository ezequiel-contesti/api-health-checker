FROM python:3.12-slim
WORKDIR /app
COPY health_checker.py ./
ENTRYPOINT ["python3", "health_checker.py"]
