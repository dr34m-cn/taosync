FROM dr34m/tao-sync:not-for-use-pyinstaller
ARG WHEEL_CACHE_DIR
COPY requirements.in requirements.txt dockerfiles/verify_requirements_lock.py ./
RUN --mount=type=bind,source=${WHEEL_CACHE_DIR},target=/wheels-cache,readonly \
	set -eux; \
	python verify_requirements_lock.py requirements.in requirements.txt; \
	mkdir -p /wheels; \
	python -m pip wheel \
		--no-cache-dir \
		--prefer-binary \
		--find-links /wheels-cache \
		--wheel-dir /wheels \
		-r requirements.in \
		-c requirements.txt; \
	python -m pip install \
		--no-cache-dir \
		--ignore-installed \
		--no-deps \
		--no-index \
		--find-links /wheels \
		-r requirements.txt; \
	python -m pip check; \
	rm verify_requirements_lock.py
