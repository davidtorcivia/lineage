FROM python:3.13-alpine
WORKDIR /app
COPY serve.py login.html ./
ENV DATA=/data PYTHONUNBUFFERED=1
USER nobody
EXPOSE 8080
CMD ["python", "serve.py", "8080"]
