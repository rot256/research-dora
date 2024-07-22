#!/bin/bash

# takes the destination as a argument
rsync -avz --exclude 'target' --exclude '.git' --exclude '.gitignore' --exclude 'result-*.json' --exclude '__pycache__' ../ $1:~/dora
