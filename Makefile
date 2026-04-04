DOCKER_IMAGE ?= tmunzer/mist-automation
DOCKER_TAG   ?= latest
FRONTEND_DIR  = frontend
BACKEND_DIR   = backend
STATIC_DIR    = $(BACKEND_DIR)/app/frontend/static
INDEX_DIR     = $(BACKEND_DIR)/app/frontend

.PHONY: angular clean docker all

# Build Angular frontend and copy output into the backend static directory
angular:
	cd $(FRONTEND_DIR) && npx ng build --deploy-url static/
	mkdir -p $(STATIC_DIR)
	rm -rf $(STATIC_DIR)/*
	cp -r $(FRONTEND_DIR)/dist/frontend/browser/* $(STATIC_DIR)/
	mv $(STATIC_DIR)/index.html $(INDEX_DIR)/index.html

# Build the Docker image (runs angular first)
docker: angular
	docker buildx build --platform linux/amd64 -t $(DOCKER_IMAGE):$(DOCKER_TAG) .

# Shorthand: build everything
all: docker

# Remove Angular build artifacts and copied static files
clean:
	rm -rf $(FRONTEND_DIR)/dist
	rm -rf $(STATIC_DIR)
	rm -f $(INDEX_DIR)/index.html
