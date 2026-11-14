# code-viz runner "node" (runners/node/Dockerfile).
# Full manual: the header of code-viz (`code-viz readme`, or README.md), sections 2 Architecture (Runners), 7 Kinds of visualization, 15 Where things run and safety.
# Node.js 22.23.5, for JavaScript examples (output only).
#
# How it is used: code-viz builds this image as code-viz-node:<hash of this file> the first time an
# example needs it (docker build --network host: downloads time out on minipc's default bridge),
# runs examples in throwaway containers with --network none, --cpus 1, --memory 1g, --pids-limit 256,
# mounting the tracers read-only at /viz/tracers and the job folder at /work (tracers/driver.py and
# tracers/langrun.py), and removes the image afterwards unless --keep-images.
# Change the pinned versions here; the new hash makes code-viz rebuild. python3 is only the driver.
FROM node:22.23.5-trixie-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends python3 && rm -rf /var/lib/apt/lists/*
WORKDIR /work
