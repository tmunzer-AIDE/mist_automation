DOCKER_IMAGE    ?= tmunzer/mist-automation
VERSION         ?=
FRONTEND_DIR     = frontend
BACKEND_DIR      = backend
STATIC_DIR       = $(BACKEND_DIR)/app/frontend/static
INDEX_DIR        = $(BACKEND_DIR)/app/frontend

.PHONY: angular clean docker publish all set-version licenses

# Build Angular frontend and copy output into the backend static directory
angular:
	cd $(FRONTEND_DIR) && npx ng build --deploy-url static/
	mkdir -p $(STATIC_DIR)
	rm -rf $(STATIC_DIR)/*
	cp -r $(FRONTEND_DIR)/dist/frontend/browser/* $(STATIC_DIR)/
	mv $(STATIC_DIR)/index.html $(INDEX_DIR)/index.html

# Build the Docker image tagged with version + latest
docker: angular licenses
	docker buildx build --platform linux/amd64 \
		-t $(DOCKER_IMAGE):$(or $(VERSION),$(shell grep '^version' $(BACKEND_DIR)/pyproject.toml | sed 's/version = "//;s/"//')) \
		-t $(DOCKER_IMAGE):latest .

# Update version in pyproject.toml, package.json, and Chart.yaml
set-version:
ifeq ($(VERSION),)
	$(error VERSION is not set. Usage: make set-version VERSION=x.y.z)
endif
	@echo "Updating version to $(VERSION)..."
	sed -i '' 's/^version = ".*"/version = "$(VERSION)"/' $(BACKEND_DIR)/pyproject.toml
	sed -i '' 's/^__version__ = ".*"/__version__ = "$(VERSION)"/' $(BACKEND_DIR)/app/__init__.py
	cd $(FRONTEND_DIR) && npm version $(VERSION) --no-git-tag-version --allow-same-version
	sed -i '' 's/^version: .*/version: $(VERSION)/' helm/mist-automation/Chart.yaml
	sed -i '' 's/^appVersion: .*/appVersion: "$(VERSION)"/' helm/mist-automation/Chart.yaml
	sed -i '' 's/^  version: ".*"/  version: "$(VERSION)"/' helm/mist-automation/values.yaml
	@echo "Version updated to $(VERSION) in all files."

# Push both tags to Docker Hub (requires VERSION parameter)
publish: set-version docker
ifeq ($(VERSION),)
	$(error VERSION is not set. Usage: make publish VERSION=x.y.z)
endif
	docker push $(DOCKER_IMAGE):$(VERSION)
	docker push $(DOCKER_IMAGE):latest

# Shorthand: build and push
all: publish

# Generate third-party licenses JSON from backend (pip-licenses) and frontend (license-checker)
licenses:
	@echo "Collecting backend licenses..."
	@cd $(BACKEND_DIR) && \
		.venv/bin/pip install pip-licenses --quiet && \
		.venv/bin/pip-licenses --format=json --with-urls --with-authors --ignore-packages mist-automation-backend > /tmp/mist_backend_licenses.json
	@echo "Collecting frontend licenses..."
	@cd $(FRONTEND_DIR) && \
		npx --yes license-checker --json --excludePrivatePackages > /tmp/mist_frontend_licenses.json
	@mkdir -p licenses
	@python3 scripts/generate_licenses.py \
		/tmp/mist_backend_licenses.json \
		/tmp/mist_frontend_licenses.json \
		licenses/licenses.json
	@cp licenses/licenses.json $(FRONTEND_DIR)/src/assets/licenses.json
	@echo "Done."

# Remove Angular build artifacts and copied static files
clean:
	rm -rf $(FRONTEND_DIR)/dist
	rm -rf $(STATIC_DIR)
	rm -f $(INDEX_DIR)/index.html
