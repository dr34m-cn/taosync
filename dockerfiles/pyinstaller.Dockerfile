FROM dr34m/tao-sync:not-for-use-python
RUN apk add --no-cache \
        binutils build-base cargo zlib-dev \
        libffi-dev openssl-dev pkgconf \
    && python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir pyinstaller