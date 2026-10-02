# 1. Use the official Python base image
FROM python:3.10

# 2. Set the working directory inside the container
WORKDIR /code

# 3. Copy just the requirements first to cache the installations
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# 4. Hugging Face Spaces requires running as a non-root user for security
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

# 5. Copy your application code into the container
COPY --chown=user . $HOME/app

# 6. Start FastAPI on port 7860 
# NOTE: If your FastAPI app is inside main.py instead of api.py, change "api:app" to "main:app"
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "7860"]