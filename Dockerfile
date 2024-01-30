FROM python:3.8.18-bookworm
ARG DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    wget \
    git \
    build-essential \
    libgl1 \
    libssl-dev \
    libffi-dev \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    libjpeg-dev \
    libpng-dev \
    unzip \
    ffmpeg

# Change the working directory to SadTalker
WORKDIR /app/SadTalker

COPY . .

# Install PyTorch with CUDA 11.3 support
RUN pip install torch==1.12.1+cu113 torchvision==0.13.1+cu113 torchaudio==0.12.1 --extra-index-url https://download.pytorch.org/whl/cu113

# Install dependencies from requirements.txt
RUN pip install -r requirements.txt

# Download models using the provided script
RUN chmod +x scripts/download_models.sh && scripts/download_models.sh

## Install extra packages
#RUN pip install dlib-bin git+https://github.com/TencentARC/GFPGAN

EXPOSE 5000

ENTRYPOINT ["python", "api.py"]
