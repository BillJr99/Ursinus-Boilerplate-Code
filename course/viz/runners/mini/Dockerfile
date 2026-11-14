# code-viz runner "mini" (runners/mini/Dockerfile).
# Full manual: the header of code-viz (`code-viz readme`, or README.md), sections 2 Architecture (Runners), 15 Where things run and safety.
# For the CS374 Mini language: interp= examples run the project guide's own Python interpreter here
# (python:3.12, no extra packages); flex, bison and gcc build files/examples/mininote for the others.
#
# How it is used: code-viz builds this image as code-viz-mini:<hash of this file> the first time an
# example needs it (docker build --network host: downloads time out on minipc's default bridge),
# runs examples in throwaway containers with --network none (agents: the Ollama network only),
# --cpus 1, --memory 1g, --pids-limit 256, mounting the tracers read-only at /viz/tracers and the
# job folder at /work (tracers/driver.py), and removes the image afterwards unless --keep-images.
# Change the pinned versions here; the new hash makes code-viz rebuild.
FROM python:3.12-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends flex bison gcc libc6-dev make libfl-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /work
