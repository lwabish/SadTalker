FROM python:3.8.18-bookworm
ARG DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    build-essential \
    libgl1 \
    libssl-dev \
    libffi-dev \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    libjpeg-dev \
    libpng-dev \
    ffmpeg && \
    rm -rf /var/lib/apt/lists/*
# Change the working directory to SadTalker
WORKDIR /app/SadTalker
# Install PyTorch with CUDA 11.3 support
RUN pip install torch==1.12.1+cu113 torchvision==0.13.1+cu113 torchaudio==0.12.1 --extra-index-url https://download.pytorch.org/whl/cu113
# Install dependencies from requirements.txt
COPY ./requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 5000

ENTRYPOINT ["python3", "inference.py"]
