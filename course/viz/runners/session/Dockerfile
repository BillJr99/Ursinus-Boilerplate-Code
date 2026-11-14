# code-viz runner "session" (runners/session/Dockerfile): the recorder for Simulate-mode sessions.
# Full manual: the header of code-viz (`code-viz readme`, or README.md), section 23 Simulate mode,
# sessions and recording.
#
# How it is used: `code-viz record <id>` builds this image as code-viz-session:<hash of this file>
# (docker build --network host, as for every runner) and runs tracers/sessrec.py in it, on an
# internal network beside a throwaway Docker-in-Docker sandbox (docker:27.3.1-dind). The recorder
# runs each scenario command in bash under a 100x30 pseudo-terminal, with DOCKER_HOST pointing at the
# sandbox, so `docker ...` commands talk to the sandbox's daemon, never to the host's. With a
# scenario `shell` image the commands run inside a container from that image in the sandbox instead.
# Python is only the recorder's own language: session commands run in bash, not Python.
# Pinned: python:3.12-slim and the Docker CLI from docker:27.3.1-cli; change them here and the new
# hash makes code-viz rebuild.
FROM docker:27.3.1-cli AS cli
FROM python:3.12-slim
COPY --from=cli /usr/local/bin/docker /usr/local/bin/docker
ENV PYTHONDONTWRITEBYTECODE=1 TERM=xterm
WORKDIR /work
