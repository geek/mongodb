# Makefile for shipping the container image.
# Building with the docker-compose file
# directly works just fine without this.

MAKEFLAGS += --warn-undefined-variables
.DEFAULT_GOAL := build
.PHONY: *

# we get these from CI environment if available, otherwise from git
GIT_COMMIT ?= $(shell git rev-parse --short HEAD)
GIT_BRANCH ?= $(shell git rev-parse --abbrev-ref HEAD)

namespace ?= autopilotpattern
tag := branch-$(shell basename $(GIT_BRANCH))
image := $(namespace)/mongodb
test_image := $(namespace)/mongodb-testrunner

## Display this help message
help:
	@awk '/^##.*$$/,/[a-zA-Z_-]+:/' $(MAKEFILE_LIST) | awk '!(NR%2){print $$0p}{p=$$0}' | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}' | sort

# ------------------------------------------------
# Target environment configuration

dockerLocal := DOCKER_HOST= DOCKER_TLS_VERIFY= DOCKER_CERT_PATH= docker
dockerComposeLocal := DOCKER_HOST= DOCKER_TLS_VERIFY= DOCKER_CERT_PATH= docker-compose

# if you pass `TRACE=1` into the call to `make` then the Python tests will
# run under the `trace` module (provides detailed call logging)
ifndef TRACE
python := python
else
python := python -m trace
endif


# ------------------------------------------------
# Container builds

## Builds the application container image locally
build: test-runner
	$(dockerLocal) build -t=$(image):$(tag) .

## Build the test running container
test-runner:
	$(dockerLocal) build -f test/Dockerfile -t=$(test_image):$(tag) .

## Push the current application container images to the Docker Hub
push:
	$(dockerLocal) push $(image):$(tag)
	$(dockerLocal) push $(test_image):$(tag)

## Tag the current images as 'latest' and push them to the Docker Hub
ship:
	$(dockerLocal) tag $(image):$(tag) $(image):latest
	$(dockerLocal) tag $(test_image):$(tag) $(test_image):latest
	$(dockerLocal) tag $(image):$(tag) $(image):latest
	$(dockerLocal) push $(image):$(tag)
	$(dockerLocal) push $(image):latest


# ------------------------------------------------
# Test running

## Pull the container images from the Docker Hub
pull:
	docker pull $(image):$(tag)

## Run the integration test runner.
integration-test:
	$(dockerComposeLocal) -f test-compose.yml up -d --force-recreate --build
	$(dockerComposeLocal) -f test-compose.yml logs -f test


# -------------------------------------------------------
## Tear down all project containers
teardown:
	$(dockerComposeLocal) -f test-compose.yml down

## Dump logs for each container to local disk
logs:
	docker logs my_consul_1 > consul1.log 2>&1
	docker logs my_mongodb_1 > mongodb1.log 2>&1
	docker logs my_mongodb_2 > mongodb2.log 2>&1
	docker logs my_mongodb_3 > mongodb3.log 2>&1

# -------------------------------------------------------
# helper functions for testing if variables are defined

## Print environment for build debugging
debug:
	@echo GIT_COMMIT=$(GIT_COMMIT)
	@echo GIT_BRANCH=$(GIT_BRANCH)
	@echo namespace=$(namespace)
	@echo tag=$(tag)
	@echo image=$(image)
	@echo test_image=$(test_image)
	@echo python=$(python)

check_var = $(foreach 1,$1,$(__check_var))
__check_var = $(if $(value $1),,\
	$(error Missing $1 $(if $(value 2),$(strip $2))))
